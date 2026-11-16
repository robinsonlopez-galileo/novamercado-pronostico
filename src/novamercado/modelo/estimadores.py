"""Modelos de pronóstico. Todos reciben la tabla de variables de `features.construir_features`.

- Perfil (baseline): promedio del mismo día de la semana en las últimas cuatro semanas, con
  respaldo en la media de 28 días. Simple y difícil de batir en series estables.
- Boosting: HistGradientBoostingRegressor con pérdida Poisson (ventas = conteos no negativos)
  sobre rezagos, promociones, calendario y feriados.

Cada modelo guarda el factor por familia para la cantidad sugerida y la fecha de fin de su
entrenamiento, que la compuerta usa para comparar en un periodo que ningún modelo vio.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd
from sklearn.ensemble import HistGradientBoostingRegressor

from novamercado.features import COLUMNAS, COLUMNAS_CATEGORICAS
from novamercado.modelo.costos import cantidad_sugerida

PARAMETROS_HGB = {
    "loss": "poisson", "learning_rate": 0.05, "max_iter": 400, "max_leaf_nodes": 31,
    "min_samples_leaf": 50, "l2_regularization": 1.0, "random_state": 2026,
}


@dataclass
class ModeloVentas:
    tipo: str  # "perfil" o "boosting"
    estimador: object | None = None
    factores: dict[str, float] = field(default_factory=dict)
    respaldo: dict[tuple[int, str], float] = field(default_factory=dict)
    metadatos: dict = field(default_factory=dict)
    columnas: list[str] = field(default_factory=lambda: list(COLUMNAS))

    # ----------------------------------------------------------------- ajuste
    def ajustar(self, datos: pd.DataFrame) -> ModeloVentas:
        """datos: variables + columna ventas."""
        datos = datos[datos["ventas"].notna()]
        tipo_familia = datos.groupby(["tipo_cat", "familia_id"])["ventas"].mean()
        self.respaldo = {(int(k[0]), k[1]): float(v) for k, v in tipo_familia.items()}
        if self.tipo == "boosting":
            mascara = [c in COLUMNAS_CATEGORICAS for c in self.columnas]
            self.estimador = HistGradientBoostingRegressor(categorical_features=mascara, **PARAMETROS_HGB)
            self.estimador.fit(datos[self.columnas].to_numpy(float), datos["ventas"].to_numpy(float))
        return self

    # ----------------------------------------------------------------- predicción
    def venta_esperada(self, X: pd.DataFrame) -> np.ndarray:
        respaldo = pd.Series(
            [self.respaldo.get((int(t), f), np.nan) if pd.notna(t) else np.nan
             for t, f in zip(X["tipo_cat"], X["familia_id"])], index=X.index)
        if self.tipo == "perfil":
            pred = (X["media_dia_semana_4"].fillna(X["media_28"]).fillna(X["ultimo"]).fillna(respaldo))
        else:
            pred = pd.Series(self.estimador.predict(X[self.columnas].to_numpy(float)), index=X.index)
        return np.clip(pred.fillna(respaldo).fillna(0.0).to_numpy(float), 0, None)

    def predecir(self, X: pd.DataFrame) -> pd.DataFrame:
        venta = self.venta_esperada(X)
        factor = X["familia_id"].map(self.factores).fillna(1.0).to_numpy(float)
        return pd.DataFrame({"venta_esperada": np.round(venta, 1),
                             "cantidad_sugerida": cantidad_sugerida(venta, factor)}, index=X.index)
