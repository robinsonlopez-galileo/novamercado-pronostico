"""Estado de las dependencias, medido en segundo plano cada `intervalo_salud_s` (10 s).

GET /health responde con el último resultado sin esperar a ninguna dependencia, de modo que
un MLflow caído se refleja en menos de un minuto y su regreso también.
"""

from __future__ import annotations

import logging
import threading
from collections.abc import Callable
from dataclasses import dataclass, field

import requests

from novamercado.configuracion import Configuracion
from novamercado.persistencia import repositorio as repo

log = logging.getLogger("salud")
TIEMPO_ESPERA = 3.0


@dataclass
class EstadoDependencias:
    disponibles: dict[str, bool] = field(default_factory=dict)
    errores: dict[str, str] = field(default_factory=dict)
    medido: bool = False


def _http(url: str) -> Callable[[], None]:
    def prueba() -> None:
        requests.get(url, timeout=TIEMPO_ESPERA).raise_for_status()
    return prueba


class MonitorSalud:
    def __init__(self, cfg: Configuracion, pruebas: dict[str, Callable[[], None]] | None = None):
        self.cfg = cfg
        self.pruebas = pruebas if pruebas is not None else {
            "base_de_datos": lambda: repo.ping(repo.motor(cfg.db_url)),
            "mlflow": _http(f"{cfg.mlflow_uri}/health"),
            "airflow": _http(f"{cfg.airflow_url}/api/v2/monitor/health"),
        }
        self.estado = EstadoDependencias()
        self._parar = threading.Event()

    def medir(self) -> EstadoDependencias:
        disponibles, errores = {}, {}
        for nombre, prueba in self.pruebas.items():
            try:
                prueba()
                disponibles[nombre] = True
            except Exception as e:  # noqa: BLE001
                disponibles[nombre] = False
                errores[nombre] = str(e).splitlines()[0][:160]
        self.estado = EstadoDependencias(disponibles, errores, True)
        return self.estado

    def _ciclo(self) -> None:
        while not self._parar.is_set():
            self.medir()
            self._parar.wait(self.cfg.intervalo_salud_s)

    def iniciar(self) -> None:
        threading.Thread(target=self._ciclo, name="monitor-salud", daemon=True).start()

    def detener(self) -> None:
        self._parar.set()
