"""Mantiene cargado el modelo vigente y lo cambia en caliente cuando se mueve @champion.

- Un hilo consulta el alias cada `intervalo_recarga_s` (30 s): un modelo promovido empieza a
  responder en menos de un minuto, sin reiniciar la API.
- Cada modelo cargado se copia a una caché local (volumen): si MLflow no está disponible, la
  API sigue con el modelo en memoria y, si se reinicia, arranca desde la caché.
- El cambio es atómico: una solicitud usa siempre un solo par (versión, modelo).
"""

from __future__ import annotations

import json
import logging
import shutil
import threading
from dataclasses import dataclass
from pathlib import Path

import mlflow
from mlflow import MlflowClient

from novamercado.configuracion import Configuracion
from novamercado.modelo import registro
from novamercado.modelo.estimadores import ModeloVentas

log = logging.getLogger("gestor_modelo")


@dataclass(frozen=True)
class ModeloCargado:
    nombre: str
    alias: str
    version: str
    modelo: ModeloVentas
    origen: str  # "mlflow" o "cache"


class GestorModelo:
    def __init__(self, cfg: Configuracion):
        self.cfg = cfg
        self._actual: ModeloCargado | None = None
        self._lock = threading.Lock()
        self._parar = threading.Event()
        self._hilo: threading.Thread | None = None
        self.ultimo_error: str | None = None

    # ----------------------------------------------------------------- lectura
    @property
    def actual(self) -> ModeloCargado | None:
        return self._actual

    def fijar(self, cargado: ModeloCargado) -> None:
        """Instala un modelo (también lo usan las pruebas con un modelo falso)."""
        with self._lock:
            self._actual = cargado

    # ----------------------------------------------------------------- caché
    @property
    def _puntero(self) -> Path:
        return self.cfg.dir_cache_modelo / "vigente.json"

    def cargar_desde_cache(self) -> bool:
        try:
            datos = json.loads(self._puntero.read_text(encoding="utf-8"))
            modelo = registro.cargar_modelo(str(self.cfg.dir_cache_modelo / datos["version"]))
        except Exception as e:  # noqa: BLE001
            log.info("No hay modelo en caché utilizable: %s", e)
            return False
        self.fijar(ModeloCargado(self.cfg.nombre_modelo, self.cfg.alias_vigente, datos["version"], modelo, "cache"))
        log.info("Modelo versión %s cargado desde la caché local", datos["version"])
        return True

    def _guardar_cache(self, version: str) -> Path:
        destino = self.cfg.dir_cache_modelo / version
        if not (destino / "MLmodel").exists():
            temporal = self.cfg.dir_cache_modelo / f".{version}.descarga"
            shutil.rmtree(temporal, ignore_errors=True)
            temporal.mkdir(parents=True)
            ruta = mlflow.artifacts.download_artifacts(
                artifact_uri=f"models:/{self.cfg.nombre_modelo}/{version}", dst_path=str(temporal))
            shutil.rmtree(destino, ignore_errors=True)
            Path(ruta).rename(destino)
            shutil.rmtree(temporal, ignore_errors=True)
        return destino

    # ----------------------------------------------------------------- MLflow
    def sincronizar(self) -> bool:
        """Consulta @champion y carga la versión si cambió. True si hubo cambio."""
        mlflow.set_tracking_uri(self.cfg.mlflow_uri)
        cliente = MlflowClient(self.cfg.mlflow_uri)
        mv = registro.version_por_alias(cliente, self.cfg.nombre_modelo, self.cfg.alias_vigente)
        if mv is None:
            self.ultimo_error = f"no existe {self.cfg.nombre_modelo}@{self.cfg.alias_vigente}"
            return False
        version = str(mv.version)
        if self._actual is not None and self._actual.version == version:
            return False
        self.cfg.dir_cache_modelo.mkdir(parents=True, exist_ok=True)
        ruta = self._guardar_cache(version)
        modelo = registro.cargar_modelo(str(ruta))
        self.fijar(ModeloCargado(self.cfg.nombre_modelo, self.cfg.alias_vigente, version, modelo, "mlflow"))
        self._puntero.write_text(json.dumps({"version": version}), encoding="utf-8")
        self._limpiar_cache(conservar={version})
        log.info("Modelo vigente: versión %s", version)
        return True

    def _limpiar_cache(self, conservar: set[str]) -> None:
        for d in self.cfg.dir_cache_modelo.iterdir():
            if d.is_dir() and d.name not in conservar and not d.name.startswith("."):
                shutil.rmtree(d, ignore_errors=True)

    # ----------------------------------------------------------------- hilo
    def _ciclo(self) -> None:
        while not self._parar.is_set():
            try:
                self.sincronizar()
                self.ultimo_error = None
            except Exception as e:  # noqa: BLE001 - MLflow caído no debe tumbar la API
                self.ultimo_error = str(e).splitlines()[0][:200]
                log.warning("No se pudo consultar el modelo vigente: %s", self.ultimo_error)
            espera = self.cfg.intervalo_recarga_s if self._actual else 5.0
            self._parar.wait(espera)

    def iniciar(self) -> None:
        if self._actual is None:
            self.cargar_desde_cache()
        self._hilo = threading.Thread(target=self._ciclo, name="gestor-modelo", daemon=True)
        self._hilo.start()

    def detener(self) -> None:
        self._parar.set()
