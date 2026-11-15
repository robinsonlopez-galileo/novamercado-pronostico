"""Contrato de la API con un modelo real pequeño, SQLite y dependencias falsas (sin MLflow)."""

from datetime import date

import pytest
from fastapi.testclient import TestClient

from novamercado.api.main import crear_app
from novamercado.modelo.entrenamiento import entrenar, tabla_entrenamiento
from novamercado.persistencia import repositorio as repo
from novamercado.servicio.airflow_cliente import AirflowNoDisponible
from novamercado.servicio.gestor_modelo import GestorModelo, ModeloCargado
from novamercado.servicio.salud import MonitorSalud
from tests.conftest import FAMILIAS

TODAS = [f for f, _ in FAMILIAS]


class AirflowFalso:
    def __init__(self):
        self.estados: dict[str, str] = {}
        self.disponible = True

    def disparar(self):
        if not self.disponible:
            raise AirflowNoDisponible("Airflow no responde")
        run_id = f"manual__{len(self.estados)}"
        self.estados[run_id] = "running"
        return run_id

    def estado(self, run_id):
        return self.estados.get(run_id)

    def tarea_fallida(self, run_id):
        return "entrenar_reto"


@pytest.fixture(scope="module")
def modelo(historico, catalogos):
    tabla = tabla_entrenamiento(historico, catalogos)
    return entrenar("boosting", tabla, date(2026, 1, 31), catalogos).modelo


@pytest.fixture
def entorno(cfg, modelo, historico):
    engine = repo.motor(cfg.db_url)
    repo.crear_esquema(engine)
    repo.cargar_historico(engine, historico)
    gestor = GestorModelo(cfg)
    gestor.fijar(ModeloCargado(cfg.nombre_modelo, "champion", "3", modelo, "mlflow"))
    caidas = set()
    pruebas = {n: (lambda n=n: (_ for _ in ()).throw(ConnectionError("caído")) if n in caidas else None)
               for n in ("base_de_datos", "mlflow", "airflow")}
    monitor = MonitorSalud(cfg, pruebas)
    airflow = AirflowFalso()
    app = crear_app(cfg, gestor=gestor, monitor=monitor, airflow=airflow, iniciar_hilos=False)
    with TestClient(app) as cliente:
        yield cliente, engine, gestor, monitor, airflow, caidas


def cuerpo_prediccion(**cambios):
    base = {"tienda_id": 5, "fecha": "2026-03-01",
            "familias": [{"familia_id": f, "en_promocion": 0} for f in TODAS]}
    return base | cambios


def test_prediccion_cumple_el_contrato(entorno):
    cliente, engine, *_ = entorno
    r = cliente.post("/v1/prediccion", json=cuerpo_prediccion())
    assert r.status_code == 200
    j = r.json()
    assert set(j) >= {"tienda_id", "fecha", "version_modelo", "predicciones", "calidad"}
    assert j["version_modelo"] == "3" and isinstance(j["version_modelo"], str)
    assert j["calidad"] == {"estado": "ok", "observaciones": []}
    for p in j["predicciones"]:
        assert set(p) >= {"familia_id", "venta_esperada", "cantidad_sugerida"}
        assert isinstance(p["cantidad_sugerida"], int) and p["cantidad_sugerida"] >= 0
    with engine.connect() as c:
        assert c.exec_driver_sql("select count(*) from predicciones").scalar() == len(TODAS)


def test_prediccion_corregida_y_con_advertencia(entorno):
    cliente, *_ = entorno
    r = cliente.post("/v1/prediccion", json=cuerpo_prediccion(tienda_id="T05", fecha="01/03/2026"))
    assert r.json()["calidad"]["estado"] == "corregido"
    r = cliente.post("/v1/prediccion", json=cuerpo_prediccion(familias=[{"familia_id": "abarrotes", "en_promocion": 1}]))
    j = r.json()
    assert j["calidad"]["estado"] == "advertencia" and len(j["predicciones"]) == len(TODAS)
    assert {"campo", "accion", "detalle"} <= set(j["calidad"]["observaciones"][0])


@pytest.mark.parametrize("cuerpo", [
    {"tienda_id": 99, "fecha": "2026-03-01", "familias": [{"familia_id": "abarrotes", "en_promocion": 0}]},
    {"tienda_id": 5, "fecha": "no es fecha", "familias": []},
    {"fecha": "2026-03-01", "familias": []},
    [1, 2, 3],
])
def test_rechazos_responden_422_con_detail(entorno, cuerpo):
    cliente, engine, *_ = entorno
    r = cliente.post("/v1/prediccion", json=cuerpo)
    assert r.status_code == 422 and isinstance(r.json()["detail"], str)
    with engine.connect() as c:
        assert c.exec_driver_sql("select count(*) from solicitudes where http_status = 422").scalar() == 1


def test_json_invalido_responde_422(entorno):
    cliente, *_ = entorno
    r = cliente.post("/v1/prediccion", content=b"{no es json", headers={"content-type": "application/json"})
    assert r.status_code == 422 and "detail" in r.json()


def test_observaciones_idempotentes(entorno):
    cliente, *_ = entorno
    cuerpo = {"tienda_id": 5, "fecha": "2026-03-01",
              "ventas": [{"familia_id": f, "ventas": 100 + i} for i, f in enumerate(TODAS)]}
    r1 = cliente.post("/v1/observaciones", json=cuerpo)
    assert r1.status_code == 200 and r1.json()["registros_guardados"] == len(TODAS)
    r2 = cliente.post("/v1/observaciones", json=cuerpo)
    assert r2.json() == {"registros_guardados": 0, "calidad": {"estado": "ok", "observaciones": []}}
    cuerpo["ventas"][0]["ventas"] = 7
    r3 = cliente.post("/v1/observaciones", json=cuerpo)
    assert r3.json()["registros_guardados"] == 1 and r3.json()["calidad"]["estado"] == "advertencia"


def test_observacion_se_usa_en_la_siguiente_prediccion(entorno):
    cliente, engine, *_ = entorno
    cuerpo = {"tienda_id": 5, "fecha": "2026-03-01", "ventas": [{"familia_id": "abarrotes", "ventas": 5000}]}
    cliente.post("/v1/observaciones", json=cuerpo)
    historia = repo.historia_para_predecir(engine, 5, date(2026, 3, 2), 3)
    assert 5000 in set(historia["ventas"])


def test_modelo_y_salud(entorno):
    cliente, _, gestor, monitor, _, caidas = entorno
    assert cliente.get("/modelo").json() == {"nombre": "novamercado-ventas", "alias": "champion", "version": "3"}
    monitor.medir()
    assert cliente.get("/health").json()["estado"] == "ok"
    caidas.add("mlflow")
    monitor.medir()
    j = cliente.get("/health").json()
    assert j["estado"] == "degradado" and "mlflow" in j["motivo"]
    assert cliente.post("/v1/prediccion", json=cuerpo_prediccion()).status_code == 200  # sigue respondiendo
    caidas.clear()
    monitor.medir()
    assert cliente.get("/health").json()["estado"] == "ok"
    gestor._actual = None
    assert cliente.get("/health").status_code == 503
    assert cliente.post("/v1/prediccion", json=cuerpo_prediccion()).status_code == 503


def test_reentrenamiento(entorno):
    cliente, engine, _, _, airflow, _ = entorno
    r = cliente.post("/admin/reentrenar")
    assert r.status_code == 202
    run_id = r.json()["id"]
    assert cliente.get(f"/admin/reentrenar/{run_id}").json() == {"estado": "en_curso"}
    repo.terminar_reentrenamiento(engine, run_id, estado="exitoso", promovido=True, version="4",
                                  motivo="Costo en validación 18 210 vs 19 940 del vigente")
    airflow.estados[run_id] = "success"
    j = cliente.get(f"/admin/reentrenar/{run_id}").json()
    assert j == {"estado": "exitoso", "promovido": True, "version": "4",
                 "motivo": "Costo en validación 18 210 vs 19 940 del vigente"}
    r = cliente.post("/admin/reentrenar")
    fallido = r.json()["id"]
    airflow.estados[fallido] = "failed"
    j = cliente.get(f"/admin/reentrenar/{fallido}").json()
    assert j["estado"] == "fallido" and j["promovido"] is False and j["version"] == "3"
    assert cliente.get("/admin/reentrenar/no-existe").status_code == 404
    airflow.disponible = False
    assert cliente.post("/admin/reentrenar").status_code == 503
