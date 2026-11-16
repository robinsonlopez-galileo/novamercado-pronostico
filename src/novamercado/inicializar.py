"""Inicialización del producto (servicio `inicializador` del docker compose).

Desde cero: crea el esquema, carga el histórico publicado y entrena y registra el primer modelo
(@champion). Al volver a levantarse encuentra todo hecho y termina en segundos sin repetirlo.

    python -m novamercado.inicializar
"""

from __future__ import annotations

import logging
import sys
import time

import pandas as pd
import requests

from novamercado import catalogos as cat
from novamercado import configuracion, reentrenamiento
from novamercado.modelo import registro
from novamercado.persistencia import repositorio as repo

log = logging.getLogger("inicializar")
MARCA_HISTORICO = "historico_cargado"


def esperar(nombre: str, prueba, intentos: int = 60, pausa: float = 5.0) -> None:
    for i in range(1, intentos + 1):
        try:
            prueba()
            log.info("%s disponible", nombre)
            return
        except Exception as e:  # noqa: BLE001 - se reintenta cualquier fallo de conexión
            log.info("Esperando %s (%d/%d): %s", nombre, i, intentos, str(e).splitlines()[0][:120])
            time.sleep(pausa)
    raise RuntimeError(f"{nombre} no respondió a tiempo")


def cargar_historico(cfg) -> None:
    engine = repo.motor(cfg.db_url)
    repo.crear_esquema(engine)
    if repo.leer_metadato(engine, MARCA_HISTORICO):
        log.info("El histórico ya estaba cargado; no se repite")
        return
    historico = pd.read_csv(cfg.dir_datos / "historico_ventas.csv", parse_dates=["fecha"])
    if cfg.historico_hasta:
        historico = historico[historico["fecha"] <= pd.Timestamp(cfg.historico_hasta)]
        log.info("HISTORICO_HASTA=%s: se cargan solo fechas hasta ese día", cfg.historico_hasta)
    n = repo.cargar_historico(engine, historico)
    repo.escribir_metadato(engine, MARCA_HISTORICO, f"{n} filas hasta {historico['fecha'].max().date()}")
    log.info("Histórico cargado: %d filas", n)


def asegurar_modelo(cfg) -> None:
    registro.preparar_experimento(cfg.mlflow_uri, cfg.experimento)
    from mlflow import MlflowClient

    vigente = registro.version_por_alias(MlflowClient(cfg.mlflow_uri), cfg.nombre_modelo, cfg.alias_vigente)
    if vigente is not None:
        log.info("Ya existe %s@%s (versión %s); no se reentrena", cfg.nombre_modelo,
                 cfg.alias_vigente, vigente.version)
        return
    log.info("No hay modelo vigente: se entrena y registra el primero")
    resultado = reentrenamiento.ejecutar_completo(cfg, origen="inicial")
    log.info("Modelo inicial: versión %s (%s)", resultado["version"], resultado["motivo"])


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(message)s", stream=sys.stdout)
    cfg = configuracion.obtener()
    cat.verificar_archivos(cfg.dir_datos)
    cat.cargar(str(cfg.dir_datos))
    engine = repo.motor(cfg.db_url)
    esperar("base de datos del producto", lambda: repo.ping(engine))
    cargar_historico(cfg)
    esperar("MLflow", lambda: requests.get(f"{cfg.mlflow_uri}/health", timeout=3).raise_for_status())
    asegurar_modelo(cfg)
    return 0


if __name__ == "__main__":
    sys.exit(main())
