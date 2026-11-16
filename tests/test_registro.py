"""Serialización del modelo: debe poder cargarse en la API aunque se haya entrenado en Airflow."""

import functools
import pickle
from datetime import date

from novamercado.modelo.entrenamiento import entrenar, tabla_entrenamiento
from novamercado.modelo.registro import serializar


def test_serializacion_no_depende_del_pickler_de_python(tmp_path, monkeypatch, historico, catalogos):
    """`dill` (importado por Airflow) modifica pickle._Pickler.dispatch. Se simula ese efecto y se
    comprueba que el modelo guardado no queda ligado a él."""

    def reductor_ajeno(pickler, obj):
        raise AssertionError("se usó el Pickler de Python puro")

    monkeypatch.setitem(pickle._Pickler.dispatch, functools.partial, reductor_ajeno)
    tabla = tabla_entrenamiento(historico, catalogos)
    modelo = entrenar("boosting", tabla, date(2026, 1, 31), catalogos).modelo
    ruta = tmp_path / "modelo.pkl"
    serializar(modelo, ruta)
    with open(ruta, "rb") as f:
        cargado = pickle.load(f)
    muestra = tabla.tail(10)
    assert (cargado.predecir(muestra) == modelo.predecir(muestra)).all().all()
