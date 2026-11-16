"""Política ante cada tipo de problema del catálogo (E01–E10) y ante problemas que no están en él."""

from datetime import date

import pytest

from novamercado.contrato import Calidad
from novamercado.limpieza import Rechazo, preparar_observacion, preparar_prediccion
from tests.conftest import FAMILIAS

TODAS = [f for f, _ in FAMILIAS]


def pred(**cambios):
    base = {"tienda_id": 5, "fecha": "2025-11-17",
            "familias": [{"familia_id": f, "en_promocion": 0} for f in TODAS]}
    base.update(cambios)
    return base


def obs(**cambios):
    base = {"tienda_id": 5, "fecha": "2025-11-17",
            "ventas": [{"familia_id": f, "ventas": 100 + i} for i, f in enumerate(TODAS)]}
    base.update(cambios)
    return base


def acciones(resultado):
    return [(o.campo, o.accion) for o in resultado.observaciones]


def estado(resultado):
    return Calidad.desde(resultado.observaciones).estado


def test_solicitud_valida_queda_ok(catalogos):
    r = preparar_prediccion(pred(), catalogos)
    assert r.observaciones == [] and estado(r) == "ok"
    assert r.solicitud.tienda_id == 5 and r.solicitud.fecha == date(2025, 11, 17)


def test_e01_tienda_como_texto_se_repara(catalogos):
    r = preparar_prediccion(pred(tienda_id="T05"), catalogos)
    assert r.solicitud.tienda_id == 5 and acciones(r) == [("tienda_id", "reparar")]
    assert estado(r) == "corregido"


def test_tienda_inexistente_se_rechaza(catalogos):
    with pytest.raises(Rechazo, match="no existe"):
        preparar_prediccion(pred(tienda_id=99), catalogos)


def test_e02_familia_escrita_de_otra_forma_se_repara(catalogos):
    fams = [{"familia_id": "LÁCTEOS", "en_promocion": 0}, {"familia_id": "Frutas y Verduras", "en_promocion": 1},
            {"familia_id": "abarrotes ", "en_promocion": 0}]
    r = preparar_prediccion(pred(familias=fams + [{"familia_id": f, "en_promocion": 0}
                                                  for f in ("bebidas", "panaderia", "snacks")]), catalogos)
    ids = [f.familia_id for f in r.solicitud.familias]
    assert ids[:3] == ["lacteos", "frutas_verduras", "abarrotes"]
    assert all(a == "reparar" for _, a in acciones(r))


def test_familia_parecida_se_advierte_y_desconocida_se_omite(catalogos):
    fams = [{"familia_id": f, "en_promocion": 0} for f in TODAS if f != "lacteos"]
    r = preparar_prediccion(pred(familias=fams + [{"familia_id": "lacteo", "en_promocion": 0},
                                                  {"familia_id": "ferreteria", "en_promocion": 0}]), catalogos)
    assert "lacteos" in [f.familia_id for f in r.solicitud.familias]
    assert "ferreteria" not in [f.familia_id for f in r.solicitud.familias]
    assert estado(r) == "advertencia"


def test_e03_promocion_como_texto_o_decimal_se_repara(catalogos):
    fams = [{"familia_id": f, "en_promocion": v} for f, v in zip(TODAS, ["3", 2.0, 0, 0, 0, 0])]
    r = preparar_prediccion(pred(familias=fams), catalogos)
    assert [f.en_promocion for f in r.solicitud.familias][:2] == [3, 2]
    assert estado(r) == "corregido"


def test_promocion_negativa_o_ilegible_se_advierte_con_cero(catalogos):
    fams = [{"familia_id": f, "en_promocion": v} for f, v in zip(TODAS, [-2, "muchas", None, 0, 0, 0])]
    r = preparar_prediccion(pred(familias=fams), catalogos)
    assert [f.en_promocion for f in r.solicitud.familias][:3] == [0, 0, 0]
    assert [a for _, a in acciones(r)] == ["advertir"] * 3


def test_e04_fecha_en_otro_formato_se_repara(catalogos):
    r = preparar_prediccion(pred(fecha="17/11/2025"), catalogos)
    assert r.solicitud.fecha == date(2025, 11, 17) and acciones(r) == [("fecha", "reparar")]


def test_fecha_ambigua_usa_la_referencia_de_operacion(catalogos):
    r = preparar_prediccion(pred(fecha="05/11/2025"), catalogos, referencia=lambda t: date(2025, 5, 11))
    assert r.solicitud.fecha == date(2025, 5, 11)


def test_fecha_ilegible_o_anterior_a_la_apertura_se_rechaza(catalogos):
    with pytest.raises(Rechazo):
        preparar_prediccion(pred(fecha="ayer"), catalogos)
    with pytest.raises(Rechazo, match="apertura"):
        preparar_prediccion(pred(tienda_id=10, fecha="2025-01-10"), catalogos)


def test_fecha_fuera_del_calendario_se_advierte(catalogos):
    r = preparar_prediccion(pred(fecha="2027-03-01"), catalogos)
    assert estado(r) == "advertencia"
    with pytest.raises(Rechazo):
        preparar_prediccion(pred(fecha="2030-01-01"), catalogos)


def test_e05_faltan_familias_se_completan_con_advertencia(catalogos):
    r = preparar_prediccion(pred(familias=[{"familia_id": "abarrotes", "en_promocion": 2}]), catalogos)
    assert sorted(f.familia_id for f in r.solicitud.familias) == sorted(TODAS)
    assert acciones(r) == [("familias", "advertir")]


def test_e06_familia_repetida_con_valores_distintos_usa_el_mayor(catalogos):
    fams = pred()["familias"] + [{"familia_id": "abarrotes", "en_promocion": 3}]
    r = preparar_prediccion(pred(familias=fams), catalogos)
    abarrotes = [f for f in r.solicitud.familias if f.familia_id == "abarrotes"]
    assert len(abarrotes) == 1 and abarrotes[0].en_promocion == 3
    assert estado(r) == "advertencia"


def test_familia_repetida_identica_se_repara(catalogos):
    fams = pred()["familias"] + [{"familia_id": "abarrotes", "en_promocion": 0}]
    r = preparar_prediccion(pred(familias=fams), catalogos)
    assert estado(r) == "corregido"


def test_e07_campo_renombrado_se_repara(catalogos):
    cuerpo = pred()
    cuerpo["tienda"] = cuerpo.pop("tienda_id")
    r = preparar_prediccion(cuerpo, catalogos)
    assert r.solicitud.tienda_id == 5 and acciones(r) == [("tienda", "reparar")]


def test_campos_renombrados_dentro_de_familias_y_desconocidos(catalogos):
    fams = [{"Familia": f, "promocion": 1} for f in TODAS]
    r = preparar_prediccion({"Tienda_ID": 5, "Fecha": "2025-11-17", "familias": fams, "origen": "pos"},
                            catalogos)
    assert all(f.en_promocion == 1 for f in r.solicitud.familias)
    assert ("origen", "advertir") in acciones(r)


def test_campo_obligatorio_ausente_o_contradictorio_se_rechaza(catalogos):
    cuerpo = pred()
    del cuerpo["fecha"]
    with pytest.raises(Rechazo, match="fecha"):
        preparar_prediccion(cuerpo, catalogos)
    with pytest.raises(Rechazo, match="valores distintos"):
        preparar_prediccion(pred(tienda=3), catalogos)


@pytest.mark.parametrize("cuerpo", [[], "texto", None, {"tienda_id": 5, "fecha": "2025-11-17", "familias": "x"}])
def test_cuerpos_sin_forma_se_rechazan(catalogos, cuerpo):
    with pytest.raises(Rechazo):
        preparar_prediccion(cuerpo, catalogos)


def test_familias_como_objeto_se_reparan(catalogos):
    r = preparar_prediccion(pred(familias={f: 1 for f in TODAS}), catalogos)
    assert len(r.solicitud.familias) == len(TODAS) and estado(r) == "corregido"


def test_ninguna_familia_reconocida_se_rechaza(catalogos):
    with pytest.raises(Rechazo, match="ninguna familia"):
        preparar_prediccion(pred(familias=[{"familia_id": "ferreteria", "en_promocion": 0}]), catalogos)


# --------------------------------------------------------------------------- observaciones
def test_observacion_valida(catalogos):
    r = preparar_observacion(obs(), catalogos)
    assert r.observaciones == [] and len(r.solicitud.ventas) == len(TODAS)


def test_e08_ventas_negativas_no_se_registran(catalogos):
    ventas = obs()["ventas"]
    ventas[4]["ventas"] = -4
    r = preparar_observacion(obs(ventas=ventas), catalogos)
    assert "frutas_verduras" not in [v.familia_id for v in r.solicitud.ventas]
    assert r.no_registradas == ["frutas_verduras"] and estado(r) == "advertencia"


def test_e10_numeros_con_formato_se_reparan(catalogos):
    ventas = obs()["ventas"]
    ventas[0]["ventas"], ventas[1]["ventas"] = "1,292", "50,0"
    r = preparar_observacion(obs(ventas=ventas), catalogos)
    assert [v.ventas for v in r.solicitud.ventas][:2] == [1292, 50]
    assert estado(r) == "corregido"


def test_observacion_repetida_con_valores_distintos_no_se_registra(catalogos):
    ventas = obs()["ventas"] + [{"familia_id": "abarrotes", "ventas": 5}]
    r = preparar_observacion(obs(ventas=ventas), catalogos)
    assert "abarrotes" not in [v.familia_id for v in r.solicitud.ventas]


def test_observacion_incompleta_se_advierte(catalogos):
    r = preparar_observacion(obs(ventas=[{"familia_id": "abarrotes", "ventas": 10}]), catalogos)
    assert len(r.solicitud.ventas) == 1 and estado(r) == "advertencia"
