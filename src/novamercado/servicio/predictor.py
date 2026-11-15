"""Predicción de un día: arma las variables con la historia de la base y aplica el modelo."""

from __future__ import annotations

import pandas as pd
from sqlalchemy import Engine

from novamercado.catalogos import Catalogos
from novamercado.contrato import PrediccionFamilia, SolicitudPrediccion
from novamercado.features import VENTANA_HISTORIA_DIAS, construir_features
from novamercado.modelo.estimadores import ModeloVentas
from novamercado.persistencia import repositorio as repo


def predecir(solicitud: SolicitudPrediccion, modelo: ModeloVentas, catalogos: Catalogos,
             engine: Engine) -> tuple[list[PrediccionFamilia], bool]:
    """Devuelve las predicciones y si hubo historia reciente para la tienda."""
    historia = repo.historia_para_predecir(engine, solicitud.tienda_id, solicitud.fecha,
                                           VENTANA_HISTORIA_DIAS)
    objetivos = pd.DataFrame([{"tienda_id": solicitud.tienda_id, "fecha": pd.Timestamp(solicitud.fecha),
                               "familia_id": f.familia_id, "en_promocion": f.en_promocion}
                              for f in solicitud.familias])
    variables = construir_features(historia, objetivos, catalogos)
    salida = modelo.predecir(variables)
    predicciones = [
        PrediccionFamilia(familia_id=f, venta_esperada=float(v), cantidad_sugerida=int(c))
        for f, v, c in zip(objetivos["familia_id"], salida["venta_esperada"], salida["cantidad_sugerida"])
    ]
    con_historia = bool(len(historia)) and (historia["fecha"].max() >= pd.Timestamp(solicitud.fecha) - pd.Timedelta(days=28))
    return predicciones, con_historia
