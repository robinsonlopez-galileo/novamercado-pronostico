"""Registro de experimentos y modelos en MLflow, con su linaje.

El modelo se guarda como pyfunc ("models from code", ver pyfunc_modelo.py): la API lo carga con
`models:/<nombre>@champion` sin saber qué tipo de modelo hay detrás. La firma fija las columnas
de entrada.
"""

from __future__ import annotations

import hashlib
import json
import pickle
import tempfile
from pathlib import Path

import mlflow
import pandas as pd
from mlflow import MlflowClient
from mlflow.models import infer_signature

import novamercado
from novamercado.features import COLUMNAS
from novamercado.modelo.estimadores import PARAMETROS_HGB, ModeloVentas

ARCHIVO_PYFUNC = Path(__file__).with_name("pyfunc_modelo.py")


def serializar(modelo: ModeloVentas, ruta: Path) -> None:
    """Guarda el modelo con el Pickler de C (protocolo 5).

    joblib usa el Pickler de Python puro, que la librería `dill` modifica al importarse (Airflow
    la importa): un modelo guardado así dentro de Airflow quedaría dependiendo de dill y la API
    no podría cargarlo. El Pickler de C no se ve afectado."""
    with open(ruta, "wb") as f:
        pickle.Pickler(f, protocol=5).dump(modelo)


def huella_datos(ventas: pd.DataFrame) -> str:
    """Huella de las filas usadas: permite saber si dos entrenamientos vieron los mismos datos."""
    contenido = pd.util.hash_pandas_object(
        ventas[["tienda_id", "fecha", "familia_id", "ventas"]].sort_values(
            ["tienda_id", "fecha", "familia_id"]), index=False)
    return hashlib.sha256(contenido.values.tobytes()).hexdigest()[:16]


def preparar_experimento(uri: str, experimento: str) -> None:
    mlflow.set_tracking_uri(uri)
    mlflow.set_experiment(experimento)


def registrar_modelo(modelo: ModeloVentas, ejemplo: pd.DataFrame, nombre_run: str, nombre_modelo: str,
                     parametros: dict, metricas: dict, etiquetas: dict) -> tuple[str, str]:
    """Crea un run con parámetros, métricas y linaje, y registra una versión nueva.

    Devuelve (run_id, versión)."""
    entrada = ejemplo[COLUMNAS + ["familia_id"]].head(50).reset_index(drop=True)
    salida = modelo.predecir(entrada)
    firma = infer_signature(entrada, salida)
    with tempfile.TemporaryDirectory() as tmp, mlflow.start_run(run_name=nombre_run) as run:
        ruta = Path(tmp) / "modelo.pkl"
        serializar(modelo, ruta)
        (Path(tmp) / "factores_cantidad_sugerida.json").write_text(
            json.dumps(modelo.factores, indent=2, ensure_ascii=False), encoding="utf-8")
        mlflow.log_params({"modelo.tipo": modelo.tipo,
                           **({f"hgb.{k}": v for k, v in PARAMETROS_HGB.items()} if modelo.tipo == "boosting" else {}),
                           **parametros})
        mlflow.log_metrics({k: float(v) for k, v in metricas.items()})
        mlflow.set_tags({"codigo_version": novamercado.__version__, **etiquetas,
                         **{f"meta.{k}": v for k, v in modelo.metadatos.items()}})
        mlflow.log_artifact(str(Path(tmp) / "factores_cantidad_sugerida.json"))
        info = mlflow.pyfunc.log_model(
            name="modelo", python_model=str(ARCHIVO_PYFUNC), artifacts={"modelo": str(ruta)},
            signature=firma, input_example=entrada.head(3),
            registered_model_name=nombre_modelo,
            pip_requirements=["scikit-learn==1.9.1", "pandas==3.0.5", "numpy==2.5.3"],
        )
        version = str(info.registered_model_version)
        cliente = MlflowClient()
        for k, v in {**etiquetas, **modelo.metadatos}.items():
            cliente.set_model_version_tag(nombre_modelo, version, k, str(v))
        return run.info.run_id, version


def version_por_alias(cliente: MlflowClient, nombre: str, alias: str):
    """ModelVersion con ese alias, o None si no existe."""
    try:
        return cliente.get_model_version_by_alias(nombre, alias)
    except mlflow.exceptions.MlflowException as e:
        if "not found" in str(e).lower() or "RESOURCE_DOES_NOT_EXIST" in str(e) or "does not exist" in str(e).lower():
            return None
        raise


def cargar_modelo(uri_modelo: str) -> ModeloVentas:
    """Carga el ModeloVentas detrás de un pyfunc (local o models:/...)."""
    pyfunc = mlflow.pyfunc.load_model(uri_modelo)
    return pyfunc.unwrap_python_model().modelo


def promover(cliente: MlflowClient, nombre: str, version: str, alias_vigente: str,
             alias_anterior: str, motivo: str) -> None:
    """Mueve @champion a `version`; el vigente anterior queda en @anterior."""
    previo = version_por_alias(cliente, nombre, alias_vigente)
    if previo is not None and previo.version != version:
        cliente.set_registered_model_alias(nombre, alias_anterior, previo.version)
    cliente.set_registered_model_alias(nombre, alias_vigente, version)
    cliente.set_model_version_tag(nombre, version, "decision", "promovido")
    cliente.set_model_version_tag(nombre, version, "motivo", motivo)


def descartar(cliente: MlflowClient, nombre: str, version: str, motivo: str) -> None:
    cliente.set_model_version_tag(nombre, version, "decision", "descartado")
    cliente.set_model_version_tag(nombre, version, "motivo", motivo)
