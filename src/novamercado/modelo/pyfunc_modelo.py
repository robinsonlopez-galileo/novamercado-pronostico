"""Modelo pyfunc definido como código ("models from code" de MLflow).

MLflow guarda este archivo junto al modelo y lo ejecuta al cargarlo, en lugar de deserializar
un objeto con cloudpickle. El ModeloVentas se guarda aparte con el pickle de C (ver
`registro.serializar`), que no depende de librerías instaladas solo en Airflow.
"""

from __future__ import annotations

import pickle

import mlflow
import pandas as pd
from mlflow.models import set_model


class PyfuncVentas(mlflow.pyfunc.PythonModel):
    """Entrada: variables de `features.construir_features` más familia_id.
    Salida: venta_esperada y cantidad_sugerida."""

    def load_context(self, context):
        with open(context.artifacts["modelo"], "rb") as f:
            self.modelo = pickle.load(f)

    def predict(self, context, model_input: pd.DataFrame, params=None) -> pd.DataFrame:
        return self.modelo.predecir(model_input)


set_model(PyfuncVentas())
