from datetime import date, timedelta

import numpy as np
import pandas as pd
import pytest

from novamercado.features import COLUMNAS, construir_features
from novamercado.modelo import compuerta
from novamercado.modelo.costos import cantidad_sugerida, costo_filas, elegir_factores
from novamercado.modelo.entrenamiento import entrenar, evaluar, tabla_entrenamiento


def test_sin_fuga_de_informacion(historico, catalogos):
    """Las variables de un día no cambian si se borran los datos de ese día y posteriores."""
    dia = pd.Timestamp("2026-02-10")
    objetivo = historico[(historico["fecha"] == dia) & (historico["tienda_id"] == 5)]
    completo = construir_features(historico, objetivo, catalogos)
    pasado = construir_features(historico[historico["fecha"] < dia], objetivo, catalogos)
    pd.testing.assert_frame_equal(completo[COLUMNAS], pasado[COLUMNAS])


def test_variables_usan_el_dia_anterior_y_detectan_huecos(historico, catalogos):
    dia = pd.Timestamp("2026-02-10")
    objetivo = historico[(historico["fecha"] == dia) & (historico["tienda_id"] == 1)].head(1)
    ayer = historico[(historico["fecha"] == dia - timedelta(days=1)) & (historico["tienda_id"] == 1)
                     & (historico["familia_id"] == objetivo["familia_id"].iloc[0])]["ventas"].iloc[0]
    f = construir_features(historico, objetivo, catalogos).iloc[0]
    assert f["lag_1"] == ayer and f["dias_sin_dato"] == 1
    sin_ayer = historico[historico["fecha"] != dia - timedelta(days=1)]
    g = construir_features(sin_ayer, objetivo, catalogos).iloc[0]
    assert np.isnan(g["lag_1"]) and g["dias_sin_dato"] == 2


def test_cantidad_sugerida_es_entera_no_negativa():
    assert list(cantidad_sugerida([10.2, 0, -3, np.nan], [1.0, 1.5, 1.0, 1.0])) == [11, 0, 0, 0]


def test_costo_asimetrico():
    assert list(costo_filas([10, 10], [8, 13], [2.0, 2.0], [0.5, 0.5])) == [4.0, 1.5]


def test_factor_sube_cuando_faltar_es_caro(catalogos):
    rng = np.random.default_rng(1)
    pred = np.full(2000, 100.0)
    real = rng.poisson(100, 2000)
    df = pd.DataFrame({"familia_id": ["abarrotes"] * 1000 + ["panaderia"] * 1000,
                       "venta_esperada": pred, "ventas": real})
    f = elegir_factores(df, catalogos)
    assert f["abarrotes"] > 1.0 > f["panaderia"]  # faltar abarrotes es caro; sobrar pan es caro


def test_modelo_supera_al_baseline_y_no_usa_la_ventana(historico, catalogos):
    tabla = tabla_entrenamiento(historico, catalogos)
    fin = date(2026, 1, 31)
    reto = entrenar("boosting", tabla, fin, catalogos)
    base = entrenar("perfil", tabla, fin, catalogos)
    m_reto = evaluar(reto.modelo, tabla, date(2026, 2, 1), date(2026, 2, 28), catalogos)
    m_base = evaluar(base.modelo, tabla, date(2026, 2, 1), date(2026, 2, 28), catalogos)
    assert reto.modelo.metadatos["fin_entrenamiento"] == "2026-01-31"
    assert m_reto["costo"] < m_base["costo"]
    pred = reto.modelo.predecir(tabla.head(20))
    assert (pred["cantidad_sugerida"] >= 0).all() and pred["cantidad_sugerida"].dtype.kind == "i"


@pytest.mark.parametrize("reto, vigente, base, dias, promueve", [
    (90, 100, 120, 28, True),
    (99.5, 100, 120, 28, False),   # mejora menor al 1 %
    (90, None, 120, 28, True),     # sin vigente
    (130, None, 120, 28, False),   # no supera al baseline
    (80, 100, 120, 7, False),      # ventana demasiado corta
    (None, 100, 120, 28, False),   # el reto no produjo métricas
])
def test_compuerta(reto, vigente, base, dias, promueve):
    d = compuerta.decidir(reto, vigente, base, dias)
    assert d.promover is promueve and d.motivo
