# Decisiones técnicas y de producto

Cada decisión indica la alternativa elegida, las que se descartaron y por qué. Las cifras de
operación provienen de `evidencia/` (modo de ensayo con el histórico cortado al 31 de diciembre
de 2025 y enero y febrero de 2026 reproducidos día a día).

## 1. Política ante cada tipo de problema en los datos

### Principio

| Política | Cuándo | Cómo se informa |
|---|---|---|
| **Reparar** | Existe una sola lectura posible del dato. | `accion: "reparar"`, estado `corregido`. |
| **Advertir** | Se responde, pero con un supuesto: hay varias lecturas, falta un dato secundario o se descarta parte de la solicitud. | `accion: "advertir"`, estado `advertencia`. |
| **Rechazar** | Falta o es ilegible un dato sin el cual cualquier respuesta sería inventada: la tienda, la fecha o la lista de familias. | HTTP 422 con `detail`. |

Las reglas son generales y no están atadas a los códigos del catálogo. Viven en
`src/novamercado/limpieza/` (funciones puras con pruebas). Después de limpiar, el resultado se
valida con modelos estrictos de Pydantic (`contrato.py`); si aun así no cumple el contrato, se
rechaza. Todas las solicitudes, también las rechazadas, se registran con su cuerpo original, y
cada corrección queda en la tabla `correcciones`.

### Reglas generales

| Situación | Política | Ejemplo |
|---|---|---|
| Nombre de campo distinto, pero en la lista de sinónimos (sin importar acentos, mayúsculas ni separadores) | Reparar | `"tienda"` → `tienda_id` (E07), `"Fecha"`, `"promo"` |
| Nombre de campo parecido (similitud ≥ 0.85) | Advertir | `"tienda_idd"` |
| Campo desconocido | Advertir y se ignora | `"sistema_origen": "pos-v2"` |
| Dos campos que significan lo mismo, con el mismo valor | Reparar | `tienda_id` y `tienda` iguales |
| Dos campos que significan lo mismo, con valores distintos | Rechazar | `tienda_id: 5` y `tienda: 6` |
| Falta `tienda_id`, `fecha` o `familias`/`ventas` | Rechazar | |
| El cuerpo no es un objeto JSON | Rechazar | `"hola"`, `[1, 2]`, JSON mal formado |

### Por campo

| Campo | Problema | Política | Justificación |
|---|---|---|---|
| `tienda_id` | Texto, prefijo o ceros (`"5"`, `"T05"`, `"Tienda 05"`, `5.0`) — E01 | Reparar | Contiene un solo número: lectura única. |
| | Varios números, texto sin número, decimal, booleano | Rechazar | No se puede saber a qué tienda se refiere. |
| | Tienda que no existe en `tiendas.csv` | Rechazar | Predecir para una tienda inexistente sería inventar. |
| `fecha` | ISO con hora, `AAAA/MM/DD`, `AAAAMMDD`, `17/11/2025`, `17 de noviembre de 2025` — E04 | Reparar | Lectura única. |
| | Día/mes ambiguo (`05/11/2025`) | Reparar si solo una lectura cae a ±7 días del calendario de operación de la tienda (día siguiente a su última venta registrada); si no, advertir y suponer día/mes/año, la convención local. | El servicio no usa el reloj del sistema; el calendario de operación sale de los datos. |
| | Año de dos dígitos | Advertir | Supuesto: siglo XXI. |
| | Ilegible o inválida (`"mañana"`, `2025-02-30`) | Rechazar | |
| | Anterior a la apertura de la tienda | Rechazar | La tienda no existía. |
| | Posterior al calendario de `feriados.csv` | Advertir (hasta un año) / rechazar (más) | Se supone que no es feriado. |
| | Tienda sin ventas registradas en los 28 días previos | Advertir | El pronóstico se apoya en patrones generales de la tienda y la familia. |
| `familias` | Nombre en otra forma (`"LÁCTEOS"`, `"lacteos "`, `"Frutas y Verduras"`) — E02 | Reparar | Coincide con el id o con el nombre del catálogo. |
| | Nombre parecido (`"lacteo"`) | Advertir | Coincidencia por similitud, no exacta. |
| | Familia desconocida | Advertir y se omite | No se inventa una familia. |
| | Lista como objeto `{familia: valor}` o solo nombres | Reparar (+ advertir promoción faltante) | Estructura distinta con lectura única. |
| | Faltan familias que la tienda vende — E05 | Advertir y se pronostican con `en_promocion = 0` | La tienda necesita el pronóstico de todo su piso; 0 es la moda histórica de la promoción. Se informa cuáles se completaron. |
| | Familia repetida con el mismo valor | Reparar | Duplicado exacto. |
| | Familia repetida con valores distintos — E06 | Advertir y se usa la **mayor** promoción | Si un registro reporta promoción, probablemente existe; subestimarla provoca faltantes, que en casi todas las familias cuestan más que los sobrantes. |
| | Ninguna familia reconocible | Rechazar | |
| `en_promocion` | Texto o decimal entero (`"3"`, `2.0`) — E03 | Reparar | |
| | Decimal no entero (`2.5`) | Advertir y redondear | |
| | Ambiguo (`"1.000"`: mil o uno) | Advertir y elegir la lectura plausible (≤ 100) | |
| | Mayor que 100 (el histórico llega a 19) | Advertir y acotar a 100 | |
| | Ausente, nulo, negativo o ilegible | Advertir y suponer 0 | Es un dato secundario: no justifica rechazar todo el pronóstico. |
| `ventas` (observación) | Separador de miles o coma decimal (`"1,234"`, `"812,0"`) — E10 | Reparar | Las ventas son unidades enteras: una sola lectura entera. |
| | Negativas (devoluciones) — E08 | Advertir y **no se registra** esa familia | Registrar 0 o el valor absoluto sería inventar la venta real; el modelo tolera días faltantes. |
| | Ambiguo con punto (`"1.000"`: mil o uno) | Advertir y usar la lectura entera de miles | Las ventas son unidades; se informa la otra lectura. |
| | No entera (`812,5`) | Advertir y redondear | |
| | Ausente o ilegible | Advertir y no se registra | |
| | Familia repetida con valores distintos | Advertir y no se registra | No se sabe cuál es el real. |
| | Faltan familias | Advertir | Se conserva lo registrado antes; si no hay nada, el día queda sin dato para esas familias. |
| Observación | Envío repetido idéntico — E09 | Idempotente: `registros_guardados = 0`, estado `ok` | Llave primaria (tienda, fecha, familia) con `ON CONFLICT`. |
| | Reenvío con valores distintos | Se reemplaza y se advierte con el valor anterior | El último reporte de la tienda corrige al anterior. |

## 2. Información que usa el modelo al predecir

Al pronosticar el día D se usa solo lo que se conoce antes de abrir la tienda ese día:

- **Ventas hasta D−1** (histórico publicado más observaciones registradas): rezago de un día,
  último valor conocido, medias de 7, 14, 28 y 91 días, mediana y desviación de 28 días, media
  del mismo día de la semana en las últimas cuatro semanas, tendencia (7 frente a 28 días) y
  días sin dato (detecta huecos).
- **Promoción del día D**, que llega en la solicitud, y su diferencia con la promoción media de
  los 28 días anteriores.
- **Calendario**: día de la semana, del mes y del año, mes, quincena y fin de mes; feriados
  nacionales y locales (según la ciudad de la tienda), medio día, fechas comerciales, fechas de
  pago, víspera y día posterior a un feriado.
- **Identidad**: tienda, familia y tipo de tienda como variables categóricas.

Una sola función (`features.construir_features`) arma las variables para entrenar y para
predecir; una prueba verifica que las variables de un día no cambian al borrar ese día y los
posteriores (sin fuga de información). Alternativas descartadas: usar las ventas del mismo día
(no se conocen) o variables externas (no están publicadas).

**Modelos.** El baseline es el perfil histórico: media del mismo día de la semana en las cuatro
semanas anteriores. El modelo de ML es `HistGradientBoostingRegressor` con pérdida Poisson
(ventas = conteos no negativos y asimétricos). Con el histórico completo y febrero de 2026 como
validación, el boosting redujo el costo de negocio en 35 % frente al baseline (87 409 frente a
134 330) y el WAPE de 21.5 % a 17.4 %. En el ensayo de operación (enero y febrero de 2026,
`evidencia/pruebas_operacion.md`) el servicio costó 182 894 frente a 289 002 del baseline (−37 %). Se descartaron modelos por serie (ARIMA, Prophet)
porque son 120 series con poca historia en la tienda 10, y no aprovechan la información común
entre tiendas.

## 3. Cantidad sugerida

`cantidad_sugerida = ⌈venta_esperada × factor_familia⌉`, entera y no negativa.

El factor se elige por familia minimizando el costo de `costos.csv` en una ventana de
calibración de 28 días que el modelo no vio al ajustarse. Es la solución empírica del problema
del vendedor de periódicos: el óptimo es el cuantil c_faltante / (c_faltante + c_sobrante) de la
demanda. Por eso licores (2.0 frente a 0.1) recibe un factor cercano a 1.4 y panadería (1.0
frente a 2.5) uno menor que 1. El modelo y el factor se guardan juntos en el Model Registry.

Alternativas descartadas: sugerir la venta esperada (ignora la asimetría de costos); un margen
fijo para todas las familias; regresión por cuantiles por familia (doce modelos más y poca
ganancia frente al factor calibrado).

## 4. Criterio de reemplazo del modelo

El DAG entrena un reto y lo compara con el vigente en la **misma ventana**: los últimos 28 días
conocidos, que comienzan después del fin de entrenamiento de ambos. El reto se entrena con todo
lo anterior a la ventana. La regla (`modelo/compuerta.py`, función pura con pruebas) promueve si:

1. el reto produjo métricas válidas;
2. la ventana tiene al menos 14 días;
3. el reto cuesta menos que el baseline en la ventana;
4. no hay vigente, o el reto reduce el costo del vigente en al menos 1 %.

Si se promueve, `@champion` pasa al reto y el anterior queda en `@anterior`. Si no, la versión
queda registrada con `decision: descartado` y el motivo. Un fallo en cualquier tarea no toca el
alias. Alternativas descartadas: promover siempre al más reciente (cambia de modelo por ruido);
reentrenar con la ventana incluida y comparar en validación (cada modelo se mediría en datos
distintos); mejora mínima mayor (en la simulación las mejoras reales fueron de 1.2 % a 3.2 %).

## 5. Arquitectura y operación

| Decisión | Elegida | Alternativa | Por qué |
|---|---|---|---|
| Dónde vive el modelo | Se descarga del Registry y se guarda en un volumen de caché | Dentro de la imagen | La compuerta decide la versión sin reconstruir imágenes; con la caché, la API arranca aunque MLflow no esté. |
| Cambio de modelo | Un hilo consulta `@champion` cada 30 s y cambia en caliente | Reiniciar el contenedor | Requisito: sin reinicio manual, en menos de 2 minutos. |
| Salud | Un monitor mide base, MLflow y Airflow cada 10 s; `/health` responde con la última medición | Medir en cada llamada | `/health` nunca espera a una dependencia caída; detecta caídas y regresos en segundos. |
| Bases | PostgreSQL del producto y PostgreSQL de Airflow separados; MLflow con SQLite en su volumen | Una sola base | Lo exige el enunciado; aislar fallos. |
| Primer modelo | Servicio `inicializador` que termina antes de que arranque la API | Entrenar dentro de la API | Separa responsabilidades; si ya hay `@champion`, termina en segundos sin repetir trabajo. |
| Disparo del DAG | API REST v2 de Airflow con token JWT (FAB) | Ejecutar `airflow dags trigger` | La API no necesita Airflow instalado. |
| Serialización | Pickler de C y pyfunc como código | joblib y cloudpickle | `dill`, que Airflow importa, altera el Pickler de Python puro que usa joblib; el modelo entrenado en Airflow no cargaba en la API. Hay una prueba que lo verifica. |
| Ejecutor de Airflow | LocalExecutor | Celery | Un solo DAG sin paralelismo masivo; menos servicios y memoria. |
| Código en Airflow | Copiado en la imagen | Montado desde la laptop | La versión que corre es la del tag; evita problemas de permisos en WSL. |
