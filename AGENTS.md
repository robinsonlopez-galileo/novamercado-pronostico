# AGENTS.md · NovaMercado, servicio de pronóstico diario de ventas

Archivo de contexto para agentes de programación (Claude Code, Codex, OpenCode u otros).
Laboratorio 2 de Product Development (Maestría en Data Science, Universidad Galileo): servicio
de ML en producción con FastAPI, PostgreSQL, MLflow y Airflow 3. Léelo completo antes de
cambiar código. El estudiante responsable revisa y justifica todo lo que se integra a `main`.

## Producto

Cada mañana una tienda pide el pronóstico del día por familia de producto
(`POST /v1/prediccion`) y recibe la venta esperada y la cantidad sugerida. Al día siguiente
reporta las ventas reales (`POST /v1/observaciones`). El servicio:

1. defiende el contrato: **repara, advierte o rechaza** datos defectuosos con reglas generales,
   porque llegarán problemas que no están en `catalogo_errores.md`;
2. registra en PostgreSQL las solicitudes, las predicciones, las correcciones y las
   observaciones (estas últimas de forma idempotente);
3. mejora su modelo con el DAG `reentrenamiento_modelo`, disparado por
   `POST /admin/reentrenar`, que promueve el modelo nuevo a `@champion` solo si pasa la
   compuerta de reemplazo;
4. usa el modelo nuevo sin reinicio (la API revisa `@champion` cada 30 s) y sigue respondiendo
   si MLflow se cae (`GET /health` pasa a `degradado`).

El contrato exacto está en el Anexo del enunciado y en `src/novamercado/contrato.py`. Se pueden
agregar campos a las respuestas, pero **nunca omitir ni renombrar** los del contrato.

## Estructura

| Ruta | Contenido |
|---|---|
| `src/novamercado/contrato.py` | Modelos de Pydantic del contrato (estrictos). |
| `src/novamercado/limpieza/` | Defensa del contrato: funciones puras con pruebas. Nunca dentro de los endpoints. |
| `src/novamercado/features.py` | Una sola función de variables para entrenar y para predecir. |
| `src/novamercado/modelo/` | Baseline, boosting, costos y cantidad sugerida, compuerta, registro en MLflow. |
| `src/novamercado/persistencia/` | Esquema y consultas (PostgreSQL en Docker; SQLite en pruebas). |
| `src/novamercado/servicio/` | Modelo vigente en caliente, monitor de salud y cliente REST de Airflow. |
| `src/novamercado/api/main.py` | Endpoints; solo orquestan. |
| `src/novamercado/reentrenamiento.py` | Pasos del ciclo de mejora (los llama el DAG). |
| `src/novamercado/inicializar.py` | Carga inicial y primer modelo cuando se levanta desde cero. |
| `src/novamercado/configuracion.py` | Configuración por variables de entorno. |
| `dags/reentrenamiento_modelo.py` | Solo orquestación, con la API `airflow.sdk` de Airflow 3. |
| `docker/` y `docker-compose.yml` | Dockerfiles, requirements con versiones fijas y restricciones de Airflow. |
| `tests/` | pytest; no dependen de MLflow, Airflow, Docker ni de los datos publicados. |
| `scripts/` | Verificación del DAG, simulación de la operación y exportación de evidencia. |
| `datos/` | Archivos publicados por el equipo docente (no se versionan; ver `datos/LEEME.md`). |
| `evidencia/` | Resultados de ejecutar el producto completo. |
| `README.md` · `DECISIONES.md` | Cómo levantarlo desde cero · decisiones con alternativas y justificación. |

## Comandos

```bash
pip install -r docker/requirements-dev.txt     # dependencias de desarrollo
python -m pytest -q                            # pruebas
ruff check src tests dags scripts              # estilo
PYTHONPATH=src python scripts/verificar_dag.py # DAG compatible con Airflow 3 (requiere Airflow 3.3.2)
cp .env.example .env && docker compose up -d --build   # producto completo
curl localhost:8000/health                     # debe responder "ok"
```

## Reglas que no se negocian

1. **Sin fuga de información.** El pronóstico del día D usa solo ventas hasta D−1, la promoción
   que llega en la solicitud y el calendario de `feriados.csv`.
   `tests/test_features_y_modelo.py::test_sin_fuga_de_informacion` lo verifica.
2. **Nunca usar el reloj del sistema** para validar fechas: el periodo de operación es simulado.
   El calendario de operación de cada tienda sale de los datos (día siguiente a su última venta).
3. **Toda política de limpieza nueva** va en `limpieza/`, con prueba y fila en DECISIONES.md
   (sección 1). Debe ser una regla general, no un caso del catálogo.
4. **Airflow 3.** Importar de `airflow.sdk` (`dag`, `task`, `get_current_context`). No usar
   `airflow.decorators`, `airflow.operators.python`, `days_ago`, `schedule_interval` ni
   `execution_date`. Verificar con `scripts/verificar_dag.py`.
5. **Serialización.** Usar `registro.serializar` (Pickler de C, protocolo 5), nunca joblib:
   Airflow importa `dill`, que altera el Pickler de Python puro.
6. **Versiones fijas.** scikit-learn, pandas y numpy iguales en `requirements-api.txt` y
   `requirements-airflow.txt`; imágenes con tag exacto.
7. **Datos y credenciales fuera del repositorio y de las imágenes.** `datos/` y `.env` están en
   `.gitignore`; solo se versiona `.env.example`.
8. **Reemplazo del modelo.** Solo la compuerta (`modelo/compuerta.py`) mueve `@champion`. Un
   reentrenamiento que falla o no supera el criterio no toca el modelo vigente.
9. **Cambios de comportamiento** (políticas, variables, cantidad sugerida, compuerta) se
   documentan en DECISIONES.md en el mismo Pull Request.

## Flujo de trabajo

- Ramas `feature/<tema>`, `fix/<tema>` o `docs/<tema>`; todo entra a `main` por Pull Request
  con la CI en verde (pruebas, DAG con Airflow 3.3.2, compose e imágenes).
- Commits en español, en imperativo y con prefijo (`feat:`, `fix:`, `docs:`, `test:`, `build:`,
  `ci:`).
- La versión entregada se identifica con el tag `entrega-lab2`.

## Definición de terminado

Un cambio está listo cuando pasan `pytest`, `ruff` y `verificar_dag.py`, el producto se levanta
desde cero con `docker compose up -d --build` siguiendo el README, `GET /health` responde `ok`
y la documentación refleja el cambio.
