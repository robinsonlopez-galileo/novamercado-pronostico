# NovaMercado · Servicio de pronóstico diario de ventas

Guía de desarrollo del proyecto. Laboratorio 2 de Product
Development: servicio de ML en producción con FastAPI, PostgreSQL, MLflow y Airflow 3.

## Producto
Cada mañana una tienda pide el pronóstico del día por familia (`POST /v1/prediccion`) y al día
siguiente reporta las ventas reales (`POST /v1/observaciones`). El servicio repara, advierte o
rechaza datos defectuosos, registra todo en PostgreSQL y mejora su modelo con un DAG de Airflow
que decide con un criterio explícito si el modelo nuevo reemplaza a `@champion`. El contrato
exacto está en el Anexo del enunciado y en `src/novamercado/contrato.py`: no omitir ni renombrar
campos.

## Estructura
- `src/novamercado/limpieza/`: defensa del contrato (funciones puras). Nunca en los endpoints.
- `src/novamercado/features.py`: una sola función de variables para entrenar y predecir.
- `src/novamercado/modelo/`: baseline, boosting, costos, cantidad sugerida, compuerta, MLflow.
- `src/novamercado/persistencia/`: tablas y consultas (PostgreSQL; SQLite en pruebas).
- `src/novamercado/servicio/`: modelo vigente en caliente, salud y cliente de Airflow.
- `src/novamercado/api/main.py`: endpoints; solo orquestan.
- `src/novamercado/reentrenamiento.py`: pasos del ciclo de mejora (los usa el DAG).
- `dags/reentrenamiento_modelo.py`: solo orquestación, API `airflow.sdk` de Airflow 3.
- `docker/`: Dockerfiles, requirements y restricciones de Airflow. `docker-compose.yml` en la raíz.
- `tests/`: pytest; no dependen de MLflow, Airflow, Docker ni de los datos publicados.

## Comandos
- Pruebas: `pip install -r docker/requirements-dev.txt && python -m pytest -q`
- Estilo: `ruff check src tests dags scripts`
- DAG: `PYTHONPATH=src python scripts/verificar_dag.py` (requiere Airflow 3.3.2)
- Producto: `cp .env.example .env && docker compose up -d --build`

## Reglas
1. Sin fuga de información: el día D solo usa ventas hasta D−1, la promoción de la solicitud y
   el calendario. `tests/test_features_y_modelo.py::test_sin_fuga_de_informacion` lo verifica.
2. Nunca usar el reloj del sistema para validar fechas: el periodo de operación es simulado.
3. Toda política de limpieza nueva va en `limpieza/`, con prueba y fila en DECISIONES.md.
4. Airflow 3: importar de `airflow.sdk` (`dag`, `task`, `get_current_context`). No usar
   `airflow.decorators`, `airflow.operators.python`, `days_ago`, `schedule_interval` ni
   `execution_date`. Verificar con `scripts/verificar_dag.py`.
5. Serializar modelos con `registro.serializar` (Pickler de C), nunca con joblib: Airflow
   importa `dill`, que altera el Pickler de Python puro.
6. Versiones fijas: scikit-learn, pandas y numpy iguales en `requirements-api.txt` y
   `requirements-airflow.txt`; imágenes con tag exacto.
7. Datos y credenciales fuera del repositorio: `datos/` y `.env` están en `.gitignore`.
8. Ramas `feature/<tema>` o `fix/<tema>`, Pull Request a `main`, commits en español en imperativo.
