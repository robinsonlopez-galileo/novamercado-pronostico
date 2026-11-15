"""Verifica que el DAG se importa sin errores con Airflow 3 y que tiene la estructura esperada.

    python scripts/verificar_dag.py      (requiere apache-airflow 3.x instalado; lo usa la CI)
"""

import sys

from airflow.dag_processing.dagbag import DagBag

ESPERADO = {
    "planear": set(),
    "entrenar_reto": {"planear"},
    "evaluar_vigente": {"planear"},
    "decidir": {"planear", "entrenar_reto", "evaluar_vigente"},
    "promover": {"planear", "entrenar_reto", "decidir"},
    "descartar": {"planear", "entrenar_reto", "decidir"},
    "registrar_resultado": {"planear", "entrenar_reto", "evaluar_vigente", "promover", "descartar"},
}

bolsa = DagBag(dag_folder="dags")
if bolsa.import_errors:
    sys.exit(f"Errores al importar DAGs: {bolsa.import_errors}")
dag = bolsa.dags.get("reentrenamiento_modelo")
if dag is None:
    sys.exit("No se encontró el DAG reentrenamiento_modelo")
real = {t: set(dag.get_task(t).upstream_task_ids) for t in dag.task_ids}
if real != ESPERADO:
    sys.exit(f"Estructura inesperada: {real}")
if dag.schedule is not None and str(dag.timetable.summary) not in ("None", ""):
    sys.exit("El DAG debe dispararse solo desde la API (schedule=None)")
print(f"DAG reentrenamiento_modelo OK: {len(real)} tareas, sin errores de importación")
