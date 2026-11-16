from datetime import date

import pytest

from novamercado.limpieza import valores


@pytest.mark.parametrize("entrada, esperado", [
    (5, 5), ("5", 5), ("T05", 5), ("t-5", 5), ("Tienda 5", 5), ("#7", 7), (" 05 ", 5), (5.0, 5),
])
def test_tienda_reparable(entrada, esperado):
    r = valores.tienda_id(entrada)
    assert r.valor == esperado
    assert (r.accion is None) == (type(entrada) is int)


@pytest.mark.parametrize("entrada", [True, None, 5.5, "T5-2", "cinco", "-5", [5], {"id": 5}, ""])
def test_tienda_ambigua_se_rechaza(entrada):
    with pytest.raises(ValueError):
        valores.tienda_id(entrada)


@pytest.mark.parametrize("entrada, esperado, accion", [
    (994, 994, None), ("994", 994, "reparar"), ("1,234", 1234, "reparar"), ("812,0", 812, "reparar"),
    (2.0, 2, "reparar"), ("1.234", 1234, "reparar"), ("1.234,0", 1234, "reparar"),
    ("1,234.0", 1234, "reparar"), (2.6, 3, "advertir"), ("12,5", 12, "advertir"), (" 7 ", 7, "reparar"),
])
def test_enteros(entrada, esperado, accion):
    r = valores.entero_no_negativo(entrada)
    assert (r.valor, r.accion) == (esperado, accion)


@pytest.mark.parametrize("entrada", [-4, "-4", "abc", None, True, float("nan"), "1,2,3"])
def test_enteros_invalidos(entrada):
    with pytest.raises(ValueError):
        valores.entero_no_negativo(entrada)


@pytest.mark.parametrize("entrada, esperado, accion", [
    ("2025-11-17", date(2025, 11, 17), None),
    ("2025-11-17T00:00:00", date(2025, 11, 17), "reparar"),
    ("2025-11-17 08:30:00Z", date(2025, 11, 17), "reparar"),
    ("17/11/2025", date(2025, 11, 17), "reparar"),
    ("11/17/2025", date(2025, 11, 17), "reparar"),
    ("2025/11/17", date(2025, 11, 17), "reparar"),
    ("20251117", date(2025, 11, 17), "reparar"),
    (20251117, date(2025, 11, 17), "reparar"),
    ("17 de noviembre de 2025", date(2025, 11, 17), "reparar"),
    ("17-nov-2025", date(2025, 11, 17), "reparar"),
    ("05/11/2025", date(2025, 11, 5), "advertir"),  # ambigua sin referencia: día/mes
])
def test_fechas(entrada, esperado, accion):
    r = valores.fecha(entrada)
    assert (r.valor, r.accion) == (esperado, accion)


def test_fecha_ambigua_se_desempata_con_el_calendario_de_operacion():
    r = valores.fecha("05/11/2025", referencia=date(2025, 5, 11))
    assert r.valor == date(2025, 5, 11) and r.accion == "reparar"


@pytest.mark.parametrize("entrada", ["2025-02-30", "31/02/2025", "mañana", "", 17, None, "2025-13-01"])
def test_fechas_invalidas(entrada):
    with pytest.raises(ValueError):
        valores.fecha(entrada)


def test_numero_ambiguo_se_advierte_y_usa_la_lectura_plausible():
    r = valores.entero_no_negativo("1.000", maximo=100)  # mil o uno: en promociones, uno
    assert (r.valor, r.accion) == (1, "advertir")
    r = valores.entero_no_negativo("1.000")  # en ventas, mil
    assert (r.valor, r.accion) == (1000, "advertir")


def test_valor_fuera_de_rango_se_acota_y_advierte():
    r = valores.entero_no_negativo(150, maximo=100)
    assert (r.valor, r.accion) == (100, "advertir")
