"""Cliente mínimo de la API REST v2 de Airflow 3 (disparar el DAG y consultar su estado)."""

from __future__ import annotations

import threading

import requests

from novamercado.configuracion import Configuracion

TIEMPO_ESPERA = 10

# Estados de un DagRun de Airflow -> estado del contrato.
ESTADOS = {"queued": "en_curso", "running": "en_curso", "success": "exitoso", "failed": "fallido"}


class AirflowNoDisponible(RuntimeError):
    pass


class ClienteAirflow:
    def __init__(self, cfg: Configuracion):
        self.cfg = cfg
        self._token: str | None = None
        self._lock = threading.Lock()

    def _obtener_token(self) -> str:
        r = requests.post(f"{self.cfg.airflow_url}/auth/token",
                          json={"username": self.cfg.airflow_usuario, "password": self.cfg.airflow_clave},
                          timeout=TIEMPO_ESPERA)
        if r.status_code >= 400:
            raise AirflowNoDisponible(f"Airflow rechazó las credenciales ({r.status_code})")
        return r.json()["access_token"]

    def _pedir(self, metodo: str, ruta: str, **kwargs) -> requests.Response:
        url = f"{self.cfg.airflow_url}{ruta}"
        for intento in range(2):
            with self._lock:
                if self._token is None:
                    self._token = self._obtener_token()
                token = self._token
            r = requests.request(metodo, url, headers={"Authorization": f"Bearer {token}"},
                                 timeout=TIEMPO_ESPERA, **kwargs)
            if r.status_code == 401 and intento == 0:
                self._token = None
                continue
            return r
        return r

    def disparar(self) -> str:
        """Crea un DagRun del DAG de reentrenamiento. Devuelve su dag_run_id."""
        try:
            r = self._pedir("POST", f"/api/v2/dags/{self.cfg.dag_id}/dagRuns",
                            json={"logical_date": None, "conf": {}})
        except requests.RequestException as e:
            raise AirflowNoDisponible(f"Airflow no responde: {e}") from e
        if r.status_code >= 400:
            raise AirflowNoDisponible(f"Airflow no pudo iniciar el DAG ({r.status_code}): {r.text[:200]}")
        return r.json()["dag_run_id"]

    def estado(self, dag_run_id: str) -> str | None:
        """Estado de Airflow del DagRun (queued, running, success, failed) o None si no existe."""
        r = self._pedir("GET", f"/api/v2/dags/{self.cfg.dag_id}/dagRuns/{requests.utils.quote(dag_run_id, safe='')}")
        if r.status_code == 404:
            return None
        r.raise_for_status()
        return r.json()["state"]

    def tarea_fallida(self, dag_run_id: str) -> str | None:
        r = self._pedir("GET", f"/api/v2/dags/{self.cfg.dag_id}/dagRuns/"
                               f"{requests.utils.quote(dag_run_id, safe='')}/taskInstances")
        if r.status_code >= 400:
            return None
        fallidas = [ti["task_id"] for ti in r.json().get("task_instances", [])
                    if ti.get("state") in ("failed", "upstream_failed")]
        return fallidas[0] if fallidas else None
