"""Configuración del producto. Todo se lee de variables de entorno; nada va escrito en el código."""

from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import date
from functools import lru_cache
from pathlib import Path

# MLflow debe fallar rápido cuando el servidor no responde: la API no puede quedarse esperando.
os.environ.setdefault("MLFLOW_HTTP_REQUEST_TIMEOUT", "5")
os.environ.setdefault("MLFLOW_HTTP_REQUEST_MAX_RETRIES", "0")
os.environ.setdefault("MLFLOW_DISABLE_AGENT_HINT", "1")


def _fecha_opcional(valor: str | None) -> date | None:
    return date.fromisoformat(valor) if valor else None


@dataclass(frozen=True)
class Configuracion:
    db_url: str
    mlflow_uri: str
    dir_datos: Path
    nombre_modelo: str = "novamercado-ventas"
    experimento: str = "novamercado-ventas"
    alias_vigente: str = "champion"
    alias_anterior: str = "anterior"
    airflow_url: str = "http://airflow-apiserver:8080"
    airflow_usuario: str = "admin"
    airflow_clave: str = ""
    dag_id: str = "reentrenamiento_modelo"
    intervalo_recarga_s: float = 30.0
    intervalo_salud_s: float = 10.0
    dir_cache_modelo: Path = Path("/app/cache_modelo")
    historico_hasta: date | None = None
    dias_evaluacion: int = 28
    mejora_minima: float = 0.01


@lru_cache
def obtener() -> Configuracion:
    """Lee la configuración una sola vez por proceso."""
    e = os.environ
    return Configuracion(
        db_url=e.get("PRODUCTO_DB_URL", "sqlite:///novamercado.db"),
        mlflow_uri=e.get("MLFLOW_TRACKING_URI", "http://mlflow:5000"),
        dir_datos=Path(e.get("DATOS_DIR", "datos")),
        nombre_modelo=e.get("MODELO_NOMBRE", "novamercado-ventas"),
        experimento=e.get("MLFLOW_EXPERIMENTO", "novamercado-ventas"),
        airflow_url=e.get("AIRFLOW_API_URL", "http://airflow-apiserver:8080").rstrip("/"),
        airflow_usuario=e.get("AIRFLOW_USUARIO", "admin"),
        airflow_clave=e.get("AIRFLOW_CLAVE", ""),
        dag_id=e.get("AIRFLOW_DAG_ID", "reentrenamiento_modelo"),
        intervalo_recarga_s=float(e.get("INTERVALO_RECARGA_S", "30")),
        intervalo_salud_s=float(e.get("INTERVALO_SALUD_S", "10")),
        dir_cache_modelo=Path(e.get("DIR_CACHE_MODELO", "/app/cache_modelo")),
        historico_hasta=_fecha_opcional(e.get("HISTORICO_HASTA")),
        dias_evaluacion=int(e.get("DIAS_EVALUACION", "28")),
        mejora_minima=float(e.get("MEJORA_MINIMA", "0.01")),
    )
