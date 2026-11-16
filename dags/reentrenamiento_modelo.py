"""DAG de reentrenamiento (Airflow 3).

Se dispara desde la API con POST /admin/reentrenar (schedule=None). Solo orquesta: toda la
lógica está en `novamercado.reentrenamiento`, que también tiene pruebas.

    planear -> entrenar_reto ─┐
            -> evaluar_vigente ┴-> decidir -> [promover | descartar] -> registrar_resultado

Si una tarea falla, ninguna toca el alias @champion: el modelo vigente no cambia, y la API
informa el fallo al consultar GET /admin/reentrenar/{id}.
"""

from __future__ import annotations

from datetime import datetime, timedelta

from airflow.sdk import dag, get_current_context, task

from novamercado import configuracion, reentrenamiento
from novamercado.persistencia import repositorio as repo


def _cfg():
    return configuracion.obtener()


@dag(
    dag_id="reentrenamiento_modelo",
    schedule=None,
    start_date=datetime(2026, 1, 1),
    catchup=False,
    max_active_runs=1,
    is_paused_upon_creation=False,
    dagrun_timeout=timedelta(minutes=10),
    default_args={"retries": 0, "execution_timeout": timedelta(minutes=8)},
    tags=["novamercado", "mlflow"],
    doc_md=__doc__,
)
def reentrenamiento_modelo():
    @task
    def planear() -> dict:
        return reentrenamiento.planear(_cfg())

    @task
    def entrenar_reto(plan: dict) -> dict:
        run_id = get_current_context()["dag_run"].run_id  # p. ej. manual__2026-11-15T14:48:58.52+00:00
        marca = run_id.split("__")[-1][:19].replace(":", "")
        return reentrenamiento.entrenar_reto(_cfg(), plan, origen=f"reentrenamiento-{marca}")

    @task
    def evaluar_vigente(plan: dict) -> dict:
        return reentrenamiento.evaluar_vigente(_cfg(), plan)

    @task.branch
    def decidir(plan: dict, reto: dict, vigente: dict) -> str:
        decision = reentrenamiento.decidir(_cfg(), plan, reto, vigente)
        get_current_context()["ti"].xcom_push(key="decision", value=decision)
        return "promover" if decision["promover"] else "descartar"

    @task
    def promover(plan: dict, reto: dict) -> dict:
        decision = get_current_context()["ti"].xcom_pull(task_ids="decidir", key="decision")
        return reentrenamiento.aplicar(_cfg(), plan, reto, decision)

    @task
    def descartar(plan: dict, reto: dict) -> dict:
        decision = get_current_context()["ti"].xcom_pull(task_ids="decidir", key="decision")
        return reentrenamiento.aplicar(_cfg(), plan, reto, decision)

    @task(trigger_rule="none_failed_min_one_success")
    def registrar_resultado(plan: dict, reto: dict, vigente: dict) -> dict:
        ti = get_current_context()["ti"]
        resultado = ti.xcom_pull(task_ids="promover") or ti.xcom_pull(task_ids="descartar")
        run_id = get_current_context()["dag_run"].run_id
        repo.terminar_reentrenamiento(
            repo.motor(_cfg().db_url), run_id, estado="exitoso", promovido=resultado["promovido"],
            version=resultado["version"], motivo=resultado["motivo"],
            detalle={"plan": plan, "reto": reto, "vigente": vigente})
        return resultado

    p = planear()
    r = entrenar_reto(p)
    v = evaluar_vigente(p)
    d = decidir(p, r, v)
    ramas = [promover(p, r), descartar(p, r)]
    d >> ramas
    ramas >> registrar_resultado(p, r, v)


reentrenamiento_modelo()
