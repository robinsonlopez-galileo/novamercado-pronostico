"""Exporta evidencia de funcionamiento a evidencia/: versiones del modelo en MLflow, ejecuciones
del DAG de reentrenamiento, estado del servicio y respuestas de ejemplo de la API.

    python scripts/exportar_evidencia.py --api http://localhost:8000 \
        --mlflow http://localhost:5000 --airflow http://localhost:8080 \
        --airflow-usuario admin --airflow-clave <clave de .env>

Requiere: requests y mlflow-skinny (pip install -r docker/requirements-api.txt).
"""

from __future__ import annotations

import argparse
import json
from datetime import datetime
from pathlib import Path

import requests
from mlflow import MlflowClient

EJEMPLOS = {
    "prediccion_valida": ("/v1/prediccion", {"tienda_id": 5, "fecha": "2026-03-01", "familias": [
        {"familia_id": "abarrotes", "en_promocion": 0}, {"familia_id": "bebidas", "en_promocion": 8},
        {"familia_id": "lacteos", "en_promocion": 0}, {"familia_id": "carnes", "en_promocion": 0},
        {"familia_id": "panaderia", "en_promocion": 0}, {"familia_id": "frutas_verduras", "en_promocion": 0},
        {"familia_id": "limpieza", "en_promocion": 0}, {"familia_id": "cuidado_personal", "en_promocion": 0},
        {"familia_id": "licores", "en_promocion": 0}, {"familia_id": "snacks", "en_promocion": 0},
        {"familia_id": "bebe", "en_promocion": 0}, {"familia_id": "mascotas", "en_promocion": 0}]}),
    "prediccion_reparada": ("/v1/prediccion", {"tienda": "T05", "fecha": "01/03/2026", "familias": [
        {"familia_id": "LÁCTEOS", "en_promocion": "3"}, {"familia_id": "Frutas y Verduras", "en_promocion": 2.0},
        {"familia_id": "abarrotes", "en_promocion": 0}, {"familia_id": "bebidas", "en_promocion": 8},
        {"familia_id": "carnes", "en_promocion": 0}, {"familia_id": "panaderia", "en_promocion": 0},
        {"familia_id": "limpieza", "en_promocion": 0}, {"familia_id": "cuidado_personal", "en_promocion": 0},
        {"familia_id": "licores", "en_promocion": 0}, {"familia_id": "snacks", "en_promocion": 0},
        {"familia_id": "bebe", "en_promocion": 0}, {"familia_id": "mascotas", "en_promocion": "1"}]}),
    "prediccion_con_advertencia": ("/v1/prediccion", {"tienda_id": 5, "fecha": "2026-03-01", "familias": [
        {"familia_id": "abarrotes", "en_promocion": 0}, {"familia_id": "abarrotes", "en_promocion": 3},
        {"familia_id": "lacteo", "en_promocion": 1}]}),
    "prediccion_rechazada_tienda": ("/v1/prediccion", {"tienda_id": 99, "fecha": "2026-03-01", "familias": [
        {"familia_id": "abarrotes", "en_promocion": 0}]}),
    "prediccion_rechazada_fecha": ("/v1/prediccion", {"tienda_id": 5, "fecha": "mañana", "familias": [
        {"familia_id": "abarrotes", "en_promocion": 0}]}),
    "observacion_con_problemas": ("/v1/observaciones", {"tienda_id": "5", "fecha": "2026-03-01T00:00:00",
        "ventas": [{"familia_id": "abarrotes", "ventas": "1,234"}, {"familia_id": "bebe", "ventas": "50,0"},
                   {"familia_id": "frutas_verduras", "ventas": -4}]}),
}


def _miles(x: float | None) -> str:
    return "—" if x is None else f"{x:,.0f}".replace(",", " ")


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--api", default="http://localhost:8000")
    p.add_argument("--mlflow", default="http://localhost:5000")
    p.add_argument("--airflow", default="http://localhost:8080")
    p.add_argument("--airflow-usuario", default="admin")
    p.add_argument("--airflow-clave", required=True)
    p.add_argument("--modelo", default="novamercado-ventas")
    p.add_argument("--salida", type=Path, default=Path("evidencia"))
    p.add_argument("--sin-ejemplos", action="store_true", help="no envía solicitudes de ejemplo a la API")
    a = p.parse_args()
    a.salida.mkdir(parents=True, exist_ok=True)

    # MLflow: versiones, alias, decisión y métricas de cada run
    cliente = MlflowClient(a.mlflow)
    modelo = cliente.get_registered_model(a.modelo)
    versiones = []
    for v in sorted(cliente.search_model_versions(f"name='{a.modelo}'"), key=lambda x: int(x.version)):
        run = cliente.get_run(v.run_id)
        versiones.append({
            "version": v.version, "alias": [k for k, n in modelo.aliases.items() if n == v.version],
            "creada": datetime.fromtimestamp(v.creation_timestamp / 1000).isoformat(timespec="seconds"),
            "run": run.info.run_name, "decision": v.tags.get("decision"), "motivo": v.tags.get("motivo"),
            "tipo": v.tags.get("tipo"), "fin_entrenamiento": v.tags.get("fin_entrenamiento"),
            "ventana_evaluacion": v.tags.get("ventana_evaluacion"), "huella_datos": v.tags.get("huella_datos"),
            "costo_validacion": run.data.metrics.get("costo_validacion"),
            "baseline_costo_validacion": run.data.metrics.get("baseline_costo_validacion"),
            "wape_validacion": run.data.metrics.get("wape_validacion"),
        })
    (a.salida / "mlflow_versiones.json").write_text(json.dumps(versiones, indent=2, ensure_ascii=False), encoding="utf-8")

    # Airflow: ejecuciones del DAG
    token = requests.post(f"{a.airflow}/auth/token", json={"username": a.airflow_usuario,
                                                          "password": a.airflow_clave}, timeout=10).json()["access_token"]
    h = {"Authorization": f"Bearer {token}"}
    corridas = requests.get(f"{a.airflow}/api/v2/dags/reentrenamiento_modelo/dagRuns",
                            params={"order_by": "start_date", "limit": 100}, headers=h, timeout=10).json()
    filas = []
    for c in corridas.get("dag_runs", []):
        estado = requests.get(f"{a.api}/admin/reentrenar/{c['dag_run_id']}", timeout=10).json()
        filas.append({"dag_run_id": c["dag_run_id"], "estado_airflow": c["state"], "inicio": c.get("start_date"),
                      "fin": c.get("end_date"), "respuesta_api": estado})
    (a.salida / "airflow_ejecuciones.json").write_text(json.dumps(filas, indent=2, ensure_ascii=False), encoding="utf-8")

    # API: salud, modelo y ejemplos
    estado = {"health": requests.get(f"{a.api}/health", timeout=10).json(),
              "modelo": requests.get(f"{a.api}/modelo", timeout=10).json()}
    if not a.sin_ejemplos:
        for nombre, (ruta, cuerpo) in EJEMPLOS.items():
            r = requests.post(f"{a.api}{ruta}", json=cuerpo, timeout=30)
            estado[nombre] = {"solicitud": cuerpo, "status": r.status_code, "respuesta": r.json()}
    (a.salida / "api_respuestas.json").write_text(json.dumps(estado, indent=2, ensure_ascii=False), encoding="utf-8")

    # Resumen legible
    lineas = ["# Evidencia de funcionamiento", "", f"Generada el {datetime.now():%Y-%m-%d %H:%M}.", "",
              "## Versiones del modelo en MLflow", "",
              "| Versión | Alias | Run | Fin de entrenamiento | Costo validación | Baseline | Decisión | Motivo |",
              "|---|---|---|---|---|---|---|---|"]
    for v in versiones:
        costo = _miles(v["costo_validacion"])
        base = _miles(v["baseline_costo_validacion"])
        lineas.append(f"| {v['version']} | {', '.join(v['alias']) or '—'} | {v['run']} | {v['fin_entrenamiento']} | "
                      f"{costo} | {base} | {v['decision'] or '—'} | {v['motivo'] or '—'} |")
    lineas += ["", "## Ejecuciones del DAG de reentrenamiento", "",
               "| dag_run_id | Airflow | Respuesta de GET /admin/reentrenar/{id} |", "|---|---|---|"]
    for f in filas:
        lineas.append(f"| {f['dag_run_id']} | {f['estado_airflow']} | `{json.dumps(f['respuesta_api'], ensure_ascii=False)}` |")
    lineas += ["", "## Estado del servicio", "", f"```json\n{json.dumps(estado['health'], indent=2, ensure_ascii=False)}\n```"]
    (a.salida / "RESUMEN.md").write_text("\n".join(lineas) + "\n", encoding="utf-8")
    print(f"Evidencia escrita en {a.salida}/")


if __name__ == "__main__":
    main()
