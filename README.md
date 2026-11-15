# NovaMercado · Pronóstico diario de ventas

Laboratorio 2 de **Product Development** (Maestría en Data Science, Universidad Galileo).

Servicio de inteligencia artificial que recibe solicitudes de pronóstico de las tiendas de
NovaMercado, responde con la venta esperada y la cantidad sugerida por familia de producto
aunque los datos lleguen en mal estado, registra lo que predice y lo que realmente se vende, y
mejora su modelo de forma automática. Todo se levanta con un comando.

```
                 POST /v1/prediccion · /v1/observaciones · /admin/reentrenar
  Tiendas ───────────────────────────────►  api (FastAPI, :8000)
                                             │  limpieza → variables → modelo @champion
                                             ├── postgres-producto  solicitudes, predicciones,
                                             │                      correcciones, observaciones
                                             ├── mlflow (:5000)     experimentos y Model Registry
                                             └── Airflow 3 (:8080)  DAG reentrenamiento_modelo
                                                   └─ entrena reto → compara con @champion →
                                                      promueve o descarta (la API lo carga sola)
```

## Levantar el producto desde cero

Requisitos: Docker con Docker Compose v2 (en Windows, Docker Desktop con WSL 2; ver la guía
del curso), al menos 4 GB de memoria para Docker y los puertos 8000, 5000 y 8080 libres.

```bash
git clone https://github.com/<usuario>/novamercado-pronostico.git
cd novamercado-pronostico
git checkout entrega-lab2

# 1. Datos: copiar los archivos publicados en la carpeta datos/
#    datos/tiendas.csv, familias.csv, historico_ventas.csv, feriados.csv, costos.csv
#    (catalogo_errores.md y ejemplos/ son opcionales)

# 2. Credenciales
cp .env.example .env      # y cambiar las claves

# 3. Construir y levantar
docker compose up -d --build
```

Al levantarse desde cero, el servicio `inicializador` carga el histórico en la base del
producto, entrena el baseline y el modelo de boosting, los registra en MLflow y deja el mejor
como `novamercado-ventas@champion`; termina en menos de un minuto. Luego arranca la API. Sin
contar la construcción de imágenes, el producto queda listo en pocos minutos (el límite del
enunciado es 10; Airflow es lo que más tarda en arrancar):

```bash
curl http://localhost:8000/health        # {"estado": "ok", ...}
curl http://localhost:8000/modelo        # {"nombre": "novamercado-ventas", "alias": "champion", "version": "1"}
```

Al volver a levantarlo (`docker compose down` y `docker compose up -d`, sin `-v`) conserva la
base, los experimentos, el modelo vigente y la caché: el inicializador detecta que todo existe y
termina en segundos sin repetir trabajo. Para empezar de cero: `docker compose down -v`.

| Servicio | URL | Para qué |
|---|---|---|
| API | http://localhost:8000/docs | Contrato interactivo (OpenAPI) |
| MLflow | http://localhost:5000 | Experimentos, versiones y alias |
| Airflow | http://localhost:8080 | DAG `reentrenamiento_modelo` (usuario y clave de `.env`) |

## Uso

```bash
# Pronóstico de un día (acepta datos con problemas: ver DECISIONES.md)
curl -X POST localhost:8000/v1/prediccion -H "Content-Type: application/json" -d '{
  "tienda_id": 5, "fecha": "2026-03-01",
  "familias": [{"familia_id": "abarrotes", "en_promocion": 0}, {"familia_id": "bebidas", "en_promocion": 8}]}'

# Ventas reales del día (idempotente: reenviarla devuelve registros_guardados = 0)
curl -X POST localhost:8000/v1/observaciones -H "Content-Type: application/json" -d '{
  "tienda_id": 5, "fecha": "2026-03-01", "ventas": [{"familia_id": "abarrotes", "ventas": 994}]}'

# Reentrenamiento: 202 con un id, luego se consulta su estado
curl -X POST localhost:8000/admin/reentrenar
curl localhost:8000/admin/reentrenar/<id>
```

Cuando el DAG promueve un modelo, la API lo empieza a usar en menos de 30 segundos sin
reinicio. Si MLflow se cae, la API sigue respondiendo con el modelo cargado y `GET /health`
pasa a `degradado` en segundos; vuelve a `ok` en cuanto MLflow regresa.

## Ensayo de la operación (opcional)

Para reproducir una operación real con datos conocidos se puede cortar el histórico:

```bash
echo "HISTORICO_HASTA=2025-12-31" >> .env
docker compose down -v && docker compose up -d --build
pip install requests pandas
python scripts/simular_operacion.py --desde 2026-01-01 --hasta 2026-02-28 --datos datos \
    --api http://localhost:8000 --reentrenar-cada 14 --salida evidencia/simulacion
python scripts/exportar_evidencia.py --airflow-clave <AIRFLOW_CLAVE de .env>
```

El simulador envía cada día las observaciones del día anterior y luego los pronósticos, con un
25 % de solicitudes defectuosas, pide un reentrenamiento cada 14 días y calcula el costo real de
las cantidades sugeridas. Quitar `HISTORICO_HASTA` (y `docker compose down -v`) para volver al
histórico completo.

## Evidencia de funcionamiento

La carpeta [`evidencia/`](evidencia/) contiene el resultado de ejecutar el producto completo:

- [`RESUMEN.md`](evidencia/RESUMEN.md): versiones del modelo en MLflow con su decisión y motivo,
  y las ejecuciones del DAG.
- `mlflow_versiones.json` y `airflow_ejecuciones.json`: el mismo detalle en JSON.
- `api_respuestas.json`: respuestas ante solicitudes válidas, reparadas, con advertencias y
  rechazadas.
- [`pruebas_operacion.md`](evidencia/pruebas_operacion.md): arranque desde cero, dos meses de
  operación simulada con su costo frente al baseline, reentrenamientos, caída y regreso de
  MLflow, reentrenamiento fallido, reinicio sin MLflow y reinicio completo conservando los datos.
- `simulacion/`: resumen de la operación simulada, comparación con el baseline y ejemplos de
  respuesta para cada tipo de defecto.

## Desarrollo

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r docker/requirements-dev.txt
python -m pytest -q          # no necesitan MLflow, Airflow, Docker ni los datos publicados
ruff check src tests dags scripts
```

La CI de GitHub Actions (`.github/workflows/ci.yml`) ejecuta las pruebas, importa el DAG con
Airflow 3.3.2 y verifica su estructura, valida el `docker-compose.yml` y construye las dos
imágenes. Cada cambio entra a `main` por Pull Request.

## Estructura

```
├── src/novamercado/
│   ├── api/main.py            endpoints (solo orquestan)
│   ├── limpieza/              defensa del contrato: reparar, advertir o rechazar
│   ├── contrato.py            modelos de Pydantic del contrato
│   ├── features.py            variables para entrenar y predecir (sin fuga)
│   ├── modelo/                baseline, boosting, costos, compuerta y MLflow
│   ├── persistencia/          tablas y consultas de PostgreSQL
│   ├── servicio/              modelo vigente en caliente, salud y cliente de Airflow
│   ├── reentrenamiento.py     pasos del ciclo de mejora (los usa el DAG)
│   └── inicializar.py         carga inicial y primer modelo
├── dags/reentrenamiento_modelo.py
├── docker/                    Dockerfiles, requirements y restricciones de Airflow
├── docker-compose.yml
├── tests/                     pytest
├── scripts/                   simulación, evidencia y verificación del DAG
├── datos/                     archivos publicados (no se versionan)
├── evidencia/
├── README.md · DECISIONES.md · GUIA_DESARROLLO.md
└── .env.example
```

## Problemas frecuentes

| Síntoma | Solución |
|---|---|
| `inicializador` termina con «Faltan archivos en /datos» | Copiar los CSV publicados en `datos/` (no en una subcarpeta). |
| `defina ... en .env` al ejecutar `docker compose` | Falta `cp .env.example .env`. |
| Airflow se reinicia o es muy lento | Asignar al menos 4 GB de memoria a Docker (en WSL, `.wslconfig`). |
| `POST /admin/reentrenar` responde 503 | Airflow aún está arrancando; reintentar en un minuto. |
| Puerto ocupado | Liberar 8000, 5000 u 8080, o cambiar el puerto publicado en `docker-compose.yml`. |

Integrantes: Robinson René López Hidalgo (26007448).
