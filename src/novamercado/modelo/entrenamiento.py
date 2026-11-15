"""Entrenamiento y evaluación sin MLflow (funciones puras sobre DataFrames).

Partición temporal de un entrenamiento con fin en `fin`:

    ... ajuste ...  | calibración (28 días) |          (fin)
    el modelo se ajusta, se calibra el factor de la cantidad sugerida en días que no vio,
    y luego se reajusta con todo hasta `fin` conservando ese factor.

La evaluación para decidir el reemplazo usa días posteriores a `fin`.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta

import pandas as pd

from novamercado.catalogos import Catalogos
from novamercado.features import construir_features
from novamercado.modelo.costos import cantidad_sugerida, elegir_factores, metricas
from novamercado.modelo.estimadores import ModeloVentas

DIAS_CALIBRACION = 28


def tabla_entrenamiento(ventas: pd.DataFrame, catalogos: Catalogos) -> pd.DataFrame:
    """Variables + ventas reales para todas las filas conocidas."""
    v = ventas.copy()
    v["fecha"] = pd.to_datetime(v["fecha"])
    objetivos = v.copy()
    objetivos["en_promocion"] = objetivos["en_promocion"].fillna(0)
    tabla = construir_features(v, objetivos, catalogos)
    tabla["ventas"] = v["ventas"].to_numpy(float)
    return tabla


def _entre(tabla: pd.DataFrame, desde: date | None, hasta: date | None) -> pd.DataFrame:
    m = pd.Series(True, index=tabla.index)
    if desde is not None:
        m &= tabla["fecha"] >= pd.Timestamp(desde)
    if hasta is not None:
        m &= tabla["fecha"] <= pd.Timestamp(hasta)
    return tabla[m]


@dataclass
class Resultado:
    modelo: ModeloVentas
    metricas_calibracion: dict


def entrenar(tipo: str, tabla: pd.DataFrame, fin: date, catalogos: Catalogos) -> Resultado:
    """Entrena un modelo con datos hasta `fin` (inclusive) y calibra su cantidad sugerida."""
    inicio_calib = fin - timedelta(days=DIAS_CALIBRACION - 1)
    ajuste = _entre(tabla, None, inicio_calib - timedelta(days=1))
    calib = _entre(tabla, inicio_calib, fin)
    provisional = ModeloVentas(tipo).ajustar(ajuste)
    calib = calib.assign(venta_esperada=provisional.venta_esperada(calib))
    factores = elegir_factores(calib, catalogos)

    modelo = ModeloVentas(tipo).ajustar(_entre(tabla, None, fin))
    modelo.factores = factores
    modelo.metadatos = {
        "tipo": tipo,
        "inicio_entrenamiento": tabla["fecha"].min().date().isoformat(),
        "fin_entrenamiento": fin.isoformat(),
        "inicio_calibracion": inicio_calib.isoformat(),
    }
    calib["cantidad_sugerida"] = cantidad_sugerida(
        calib["venta_esperada"], calib["familia_id"].map(factores).fillna(1.0))
    return Resultado(modelo, metricas(calib, catalogos))


def evaluar(modelo: ModeloVentas, tabla: pd.DataFrame, desde: date, hasta: date,
            catalogos: Catalogos) -> dict:
    """Métricas del modelo en [desde, hasta] (días que no debe haber usado para ajustarse)."""
    ventana = _entre(tabla, desde, hasta)
    ventana = ventana[ventana["ventas"].notna()]
    pred = modelo.predecir(ventana)
    return metricas(ventana.assign(**pred.to_dict("series")), catalogos)
