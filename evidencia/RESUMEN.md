# Evidencia de funcionamiento

Generada el 2026-11-15 09:03.

## Versiones del modelo en MLflow

| Versión | Alias | Run | Fin de entrenamiento | Costo validación | Baseline | Decisión | Motivo |
|---|---|---|---|---|---|---|---|
| 1 | — | inicial-boosting | 2025-12-03 | 113 713 | 165 098 | promovido | Costo en validación 113 713; no había modelo vigente comparable |
| 2 | — | inicial-baseline-perfil | 2025-12-03 | 165 098 | — | respaldo (baseline) | — |
| 3 | — | reentrenamiento-2026-11-15T145743-boosting | 2025-12-16 | 103 450 | 200 353 | descartado | Costo en validación 103 450 vs 104 359 del vigente: mejora menor que 1% |
| 4 | anterior | reentrenamiento-2026-11-15T145847-boosting | 2025-12-30 | 86 768 | 207 510 | promovido | Costo en validación 86 768 vs 89 643 del vigente |
| 5 | — | reentrenamiento-2026-11-15T145944-boosting | 2026-01-13 | 86 764 | 130 273 | descartado | Costo en validación 86 764 vs 87 031 del vigente: mejora menor que 1% |
| 6 | champion | reentrenamiento-2026-11-15T150046-boosting | 2026-01-27 | 85 796 | 138 489 | promovido | Costo en validación 85 796 vs 86 858 del vigente |

## Ejecuciones del DAG de reentrenamiento

| dag_run_id | Airflow | Respuesta de GET /admin/reentrenar/{id} |
|---|---|---|
| manual__2026-11-15T14:57:43.804306+00:00 | success | `{"estado": "exitoso", "promovido": false, "version": "1", "motivo": "Costo en validación 103 450 vs 104 359 del vigente: mejora menor que 1%"}` |
| manual__2026-11-15T14:58:47.070043+00:00 | success | `{"estado": "exitoso", "promovido": true, "version": "4", "motivo": "Costo en validación 86 768 vs 89 643 del vigente"}` |
| manual__2026-11-15T14:59:44.861765+00:00 | success | `{"estado": "exitoso", "promovido": false, "version": "4", "motivo": "Costo en validación 86 764 vs 87 031 del vigente: mejora menor que 1%"}` |
| manual__2026-11-15T15:00:46.958984+00:00 | success | `{"estado": "exitoso", "promovido": true, "version": "6", "motivo": "Costo en validación 85 796 vs 86 858 del vigente"}` |
| manual__2026-11-15T15:01:49.781909+00:00 | failed | `{"estado": "fallido", "promovido": false, "version": "6", "motivo": "La ejecución falló en la tarea planear; el modelo vigente no cambió"}` |

## Estado del servicio

```json
{
  "estado": "ok",
  "modelo_cargado": true,
  "version_modelo": "6",
  "dependencias": {
    "base_de_datos": true,
    "mlflow": true,
    "airflow": true
  }
}
```
