# Pruebas de operación

Ejecución de los mismos componentes del `docker-compose.yml` (PostgreSQL 16, MLflow 3.17.2,
Airflow 3.3.2 con LocalExecutor y la API) con las versiones fijadas en `docker/`, en modo de
ensayo: `HISTORICO_HASTA=2025-12-31`, de modo que enero y febrero de 2026 se reproducen como
operación nueva con `scripts/simular_operacion.py`. Para regenerar esta evidencia sobre Docker,
ver la sección «Ensayo de la operación» del README.

## Arranque desde cero

- Inicializador (carga del histórico, entrenamiento y registro de la versión 1): 34s.
- `GET /health` con estado `ok`: 59s desde el inicio, sin contar la construcción de imágenes.

## Dos meses de operación simulada

Cada día: observaciones reales del día anterior, luego un pronóstico por tienda con la
promoción real del día; 25 % de las solicitudes con un defecto al azar (tienda como texto,
fechas en otro formato, familias en mayúsculas, números con separadores, campos renombrados,
familias repetidas o faltantes, campos extra, ventas negativas). Reentrenamiento cada 14 días.

| Métrica (1 de enero a 28 de febrero de 2026) | Valor |
|---|---|
| Pronósticos evaluados contra la venta real | 7 080 |
| Costo total de las cantidades sugeridas (costos.csv) | 182 894 |
| Costo por registro | 25.832 |
| WAPE de la venta esperada | 18.1% |

Referencia en los mismos días, sin solicitudes defectuosas ni reentrenamientos
(`scripts/comparar_baseline.py`, modelos entrenados hasta 2025-12-03):

| Modelo | Costo | Costo por registro | WAPE |
|---|---|---|---|
| Baseline (perfil del mismo día de la semana) | 289 002 | 40.819 | 29.4% |
| HistGradientBoosting inicial | 180 895 | 25.55 | 17.9% |
| Servicio en operación (con defectos y reentrenamientos) | 182 894 | 25.832 | 18.1% |

El servicio cuesta 37% menos que el baseline. Frente al modelo inicial
sin defectos cuesta 1.1% más: es el efecto de los supuestos que el
servicio debe hacer ante solicitudes incompletas (familias faltantes con promoción 0, ventas
negativas no registradas).

Respuestas del servicio:

| Tipo, código HTTP y estado de calidad | Solicitudes |
|---|---|
| observacion 200 advertencia | 38 |
| observacion 200 corregido | 116 |
| observacion 200 ok | 436 |
| prediccion 200 advertencia | 29 |
| prediccion 200 corregido | 136 |
| prediccion 200 ok | 425 |

Reentrenamientos disparados con `POST /admin/reentrenar`:

| Día simulado | Estado | Promovido | Versión vigente | Motivo | Duración |
|---|---|---|---|---|---|
| 2026-01-14 | exitoso | no | 1 | Costo en validación 103 450 vs 104 359 del vigente: mejora menor que 1% | 35 s |
| 2026-01-28 | exitoso | sí | 4 | Costo en validación 86 768 vs 89 643 del vigente | 30 s |
| 2026-02-11 | exitoso | no | 4 | Costo en validación 86 764 vs 87 031 del vigente: mejora menor que 1% | 35 s |
| 2026-02-25 | exitoso | sí | 6 | Costo en validación 85 796 vs 86 858 del vigente | 30 s |

Cuando el DAG promovió las versiones 4 y 6, la API empezó a responder con ellas sin
reiniciarse (columna `version_modelo` de `simulacion/predicciones_vs_real.csv`, que se genera
localmente y no se versiona porque contiene ventas reales).

## Resiliencia

```
### 1. Caída de MLflow
degradado detectado a los 3 s
{"estado":"degradado","motivo":"mlflow no disponible (HTTPConnectionPool(host='localhost', port=5000): Max retries exceeded with url: /health (Caused by NewConnectionError(\"HTTPConnection(host='localhost', port=500)","modelo_cargado":true,"version_modelo":"6","dependencias":{"base_de_datos":true,"mlflow":false,"airflow":true}}
POST /v1/prediccion con MLflow caído: HTTP 200
POST /admin/reentrenar: {"id":"manual__2026-11-15T15:01:49.781909+00:00"}
GET /admin/reentrenar/{id}: {"estado":"fallido","promovido":false,"version":"6","motivo":"La ejecución falló en la tarea planear; el modelo vigente no cambió"}
GET /modelo: {"nombre":"novamercado-ventas","alias":"champion","version":"6"}
### 2. Reinicio de la API con MLflow caído
modelo cargado desde la caché local a los 3 s: {"nombre":"novamercado-ventas","alias":"champion","version":"6"}
POST /v1/prediccion: HTTP 200
### 3. Regreso de MLflow
ok a los 21 s de iniciar MLflow
{"estado":"ok","modelo_cargado":true,"version_modelo":"6","dependencias":{"base_de_datos":true,"mlflow":true,"airflow":true}}
### 4. Reinicio completo conservando los datos
base de datos del producto disponible
El histórico ya estaba cargado; no se repite
MLflow disponible
Ya existe novamercado-ventas@champion (versión 6); no se reentrena
salud ok a los 36 s del reinicio; GET /modelo: {"nombre":"novamercado-ventas","alias":"champion","version":"6"}
### 5. Observación repetida (idempotencia)
envío 1: registros_guardados = 2 | estado = advertencia
envío 2: registros_guardados = 0 | estado = advertencia
envío con valor corregido: {"registros_guardados":1,"calidad":{"estado":"advertencia","observaciones":[{"campo":"ventas","accion":"advertir","detalle":"no se reportaron ventas de bebidas, lacteos, carnes, panaderia, frutas_verduras, limpieza, cuidado_personal, licores, snacks, bebe, mascotas; quedan sin registrar para ese día"},{"campo":"ventas.abarrotes","accion":"advertir","detalle":"ya había ventas registradas para abarrotes (1000); se reemplazaron por 1010"}]}}
```
