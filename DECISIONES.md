# Decisiones técnicas y de producto

Cada decisión indica qué se eligió, qué alternativas se consideraron y por qué se eligió esa. Las
cifras provienen de `evidencia/` o se pueden reproducir con los datos publicados: el modo de
ensayo corta el histórico al 31 de diciembre de 2025 y reproduce enero y febrero de 2026 día por
día.

| # | Tema que pide el enunciado | Sección | Tipo |
|---|---|---|---|
| 1 | Política ante cada tipo de problema en los datos | [1](#1-política-ante-cada-tipo-de-problema-en-los-datos) | Producto |
| 2 | Información que usa el modelo al predecir | [2](#2-información-que-usa-el-modelo-al-predecir) | Técnica |
| 3 | Elección de la cantidad sugerida | [3](#3-elección-de-la-cantidad-sugerida) | Producto y técnica |
| 4 | Criterio de reemplazo del modelo | [4](#4-criterio-de-reemplazo-del-modelo) | Técnica |
| 5 | Arquitectura y operación | [5](#5-arquitectura-y-operación) | Técnica |

---

## 1. Política ante cada tipo de problema en los datos

### Decisión

Tres políticas con un criterio único, aplicadas con reglas generales (no por código de error del
catálogo) en `src/novamercado/limpieza/`, que son funciones puras con pruebas:

| Política | Criterio | Cómo se informa |
|---|---|---|
| **Reparar** | Existe una sola lectura posible del dato. | `accion: "reparar"`, estado `corregido`. |
| **Advertir** | Se responde, pero con un supuesto: hay varias lecturas, falta un dato secundario o se descarta parte de la solicitud. | `accion: "advertir"`, estado `advertencia`. |
| **Rechazar** | Falta o es ilegible un dato sin el cual cualquier respuesta sería inventada: la tienda, la fecha o la lista de familias o de ventas. | HTTP 422 con `detail`. |

Después de limpiar, el resultado se valida con modelos estrictos de Pydantic (`contrato.py`); si
aun así no cumple el contrato, se rechaza. Todas las solicitudes, incluidas las rechazadas, se
guardan con su cuerpo original, y cada corrección queda en la tabla `correcciones`.

### Alternativas consideradas

| Alternativa | Por qué se descartó |
|---|---|
| Rechazar todo lo que no cumpla el contrato al pie de la letra | La tienda se quedaría sin pronóstico por un detalle de formato (`"T05"`, `"LÁCTEOS"`) que tiene una sola lectura. El enunciado pide defender el contrato, no solo validarlo. |
| Reparar siempre con la lectura más probable, sin avisar | Oculta supuestos: si la lectura era otra, nadie se entera. Advertir mantiene la respuesta y deja el supuesto a la vista. |
| Una regla por código del catálogo (E01 a E10) | El servicio recibirá problemas que no están en el catálogo. Las reglas por tipo de dato (identificador, fecha, nombre, número) cubren casos nuevos. |
| Validar dentro de los endpoints | Lo prohíbe el enunciado y no se puede probar sin levantar la API. |

### Justificación

El criterio separa lo que tiene **una sola lectura** (reparar sin riesgo), lo que tiene **un
supuesto razonable** (responder, pero decirlo) y lo que **obligaría a inventar** (rechazar). Así
la tienda casi siempre recibe un pronóstico útil, y cada supuesto queda registrado y se puede
auditar.

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
| | Día y mes ambiguos (`05/11/2025`) | Reparar si solo una lectura cae a ±7 días del calendario de operación de la tienda (día siguiente a su última venta registrada); si no, advertir y suponer día/mes/año, la convención local. | El servicio no usa el reloj del sistema; el calendario de operación sale de los datos. |
| | Año de dos dígitos | Advertir | Supuesto: siglo XXI. |
| | Ilegible o inválida (`"mañana"`, `2025-02-30`) | Rechazar | |
| | Anterior a la apertura de la tienda | Rechazar | La tienda no existía. |
| | Posterior al calendario de `feriados.csv` | Advertir (hasta un año) / rechazar (más) | Se supone que no es feriado. |
| | Tienda sin ventas registradas en los 28 días previos | Advertir | El pronóstico se apoya en patrones generales de la tienda y la familia. |
| `familias` | Nombre en otra forma (`"LÁCTEOS"`, `"lacteos "`, `"Frutas y Verduras"`) — E02 | Reparar | Coincide con el id o con el nombre del catálogo. |
| | Nombre parecido (`"lacteo"`) | Advertir | Coincidencia por similitud, no exacta. |
| | Familia desconocida | Advertir y se omite | No se inventa una familia. |
| | Lista como objeto `{familia: valor}` o solo nombres | Reparar (y advertir si falta la promoción) | Estructura distinta con lectura única. |
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

Las pruebas de `tests/test_limpieza_solicitudes.py` y `tests/test_valores.py` cubren el catálogo
E01 a E10 y problemas que no están en él. `evidencia/api_respuestas.json` muestra respuestas
reales para cada política.

---

## 2. Información que usa el modelo al predecir

### Decisión

Al pronosticar el día D se usa solo lo que se conoce antes de abrir la tienda ese día:

| Grupo | Variables | Origen |
|---|---|---|
| **Ventas hasta D−1** | rezago de un día, último valor conocido, medias de 7, 14, 28 y 91 días, mediana y desviación de 28 días, media del mismo día de la semana en las últimas cuatro semanas, tendencia (media de 7 frente a 28 días), días con dato en los últimos 28 y días sin dato (detecta huecos) | Histórico publicado más observaciones registradas en la base del producto |
| **Promoción del día D** | `en_promocion`, su media de los 28 días anteriores y la diferencia entre ambas | La solicitud de pronóstico (las observaciones no traen promociones) |
| **Calendario** | día de la semana, del mes y del año, mes, quincena, fin de mes; feriado nacional o local (según la ciudad de la tienda), medio día, fecha comercial, fecha de pago, víspera y día posterior a un feriado, víspera de fecha comercial | `feriados.csv`, que cubre fechas posteriores al histórico |
| **Identidad** | tienda, familia y tipo de tienda como variables categóricas | `tiendas.csv` y `familias.csv` |

Una sola función, `features.construir_features`, arma las variables para entrenar y para
predecir. La prueba `test_sin_fuga_de_informacion` verifica que las variables de un día no
cambian al borrar ese día y los posteriores.

**Modelos.** El baseline es el perfil histórico: la media del mismo día de la semana en las
cuatro semanas anteriores. El modelo de ML es `HistGradientBoostingRegressor` con pérdida
Poisson (`learning_rate` 0.05, 400 iteraciones, 31 hojas, al menos 50 casos por hoja,
regularización L2 de 1.0, semilla 2026). Si una predicción no se puede calcular (por ejemplo, una serie sin
historia), se usa la media histórica por tipo de tienda y familia como respaldo.

### Alternativas consideradas

| Alternativa | Por qué se descartó |
|---|---|
| Usar las ventas del mismo día D | No se conocen al pronosticar: la observación de D llega al día siguiente. Sería fuga de información. |
| Variables externas (clima, precios, competencia) | No están publicadas y el servicio no podría obtenerlas en operación. |
| Promoción del día como variable desconocida | Sí se conoce: llega en la solicitud y es la variable que más cambia la venta de un día a otro. |
| Funciones distintas para entrenar y para servir | Riesgo de que el modelo vea en producción variables calculadas de otra forma (*training-serving skew*). |
| Un modelo por serie (ARIMA, Prophet) | Son 120 series y algunas tienen poca historia (tienda 10); no comparten información entre tiendas y familias, y entrenarlas todas alarga el reentrenamiento. |
| Pérdida cuadrática | Las ventas son conteos no negativos y asimétricos; Poisson modela mejor esa forma y no predice valores negativos. |

### Justificación

El enunciado fija qué se conoce al momento de predecir: observaciones hasta D−1, promociones de
la solicitud y el calendario. Las variables usan exactamente eso. Con el histórico completo y
febrero de 2026 como validación, el boosting con su cantidad sugerida (sección 3) costó 87 409
frente a 134 330 del baseline (−35 %), y el WAPE bajó de 21.5 % a 17.4 %. En
el ensayo de operación (enero y febrero de 2026, `evidencia/pruebas_operacion.md`) el servicio
costó 182 894 frente a 289 002 del baseline (−37 %).

---

## 3. Elección de la cantidad sugerida

### Decisión

```
cantidad_sugerida = ⌈ venta_esperada × factor_familia ⌉     (entero, no negativo)
```

El factor se elige por familia, entre 0.50 y 2.00 en pasos de 0.01, minimizando el costo de
`costos.csv` en una **ventana de calibración de 28 días que el modelo no vio** al ajustarse.
Después el modelo se reajusta con todos los datos y conserva ese factor. El modelo y sus factores
se guardan juntos en el Model Registry, así que cada versión trae su propia cantidad sugerida.

Es la solución empírica del problema del vendedor de periódicos: la cantidad óptima es el cuantil
q* = c_faltante / (c_faltante + c_sobrante) de la demanda. Factores calibrados con el histórico
completo (calibración del 1 al 28 de febrero de 2026):

| Familia | c_faltante | c_sobrante | q* | Factor |
|---|---|---|---|---|
| licores | 2.0 | 0.1 | 0.95 | 1.49 |
| bebe | 1.5 | 0.2 | 0.88 | 1.35 |
| limpieza | 1.0 | 0.1 | 0.91 | 1.34 |
| cuidado_personal | 1.0 | 0.1 | 0.91 | 1.32 |
| bebidas | 1.0 | 0.2 | 0.83 | 1.26 |
| mascotas | 1.0 | 0.2 | 0.83 | 1.23 |
| abarrotes | 1.0 | 0.2 | 0.83 | 1.22 |
| snacks | 1.0 | 0.3 | 0.77 | 1.15 |
| carnes | 1.5 | 2.0 | 0.43 | 0.98 |
| lacteos | 1.0 | 1.2 | 0.45 | 0.95 |
| frutas_verduras | 1.0 | 2.0 | 0.33 | 0.90 |
| panaderia | 1.0 | 2.5 | 0.29 | 0.84 |

El orden de los factores sigue al de q*: donde faltar cuesta más se pide de más, y donde sobrar
cuesta más (perecederos) se pide de menos.

### Alternativas consideradas

Comparación fuera de muestra: modelo entrenado hasta el 31 de enero de 2026 y evaluado en
febrero de 2026.

| Alternativa | Costo en febrero de 2026 | Por qué se descartó |
|---|---|---|
| Sugerir la venta esperada (factor 1) | 117 601 | Ignora la asimetría de costos. |
| Un margen único para todas las familias | 115 779 (−1.5 %), incluso eligiendo el mejor margen (1.04) con los datos de febrero | Una familia necesita pedir de más y otra de menos; un solo margen no sirve a ninguna. |
| **Factor por familia calibrado (elegido)** | **87 409 (−25.7 %)** | — |
| Regresión por cuantiles con un modelo por familia | — | Doce modelos más que entrenar, registrar y servir, con más tiempo de reentrenamiento y poca ganancia esperada frente al factor calibrado, que ya aproxima el cuantil. |
| Usar q* teórico sobre una distribución supuesta (normal o Poisson) | — | Requiere suponer la forma y la varianza del error, que cambian por tienda y familia; el factor empírico se ajusta a los errores reales del modelo. |

### Justificación

El enunciado pide que la cantidad sea coherente con `costos.csv`. Minimizar ese mismo costo en
días que el modelo no vio da la cantidad que mejor equilibra faltantes y sobrantes con los errores
reales del modelo. Redondear hacia arriba entrega unidades enteras sin sugerir cero cuando se
espera una venta positiva.

---

## 4. Criterio de reemplazo del modelo

### Decisión

El DAG `reentrenamiento_modelo` entrena un reto con los datos de la base del producto (histórico
más observaciones) y lo compara con el vigente en la **misma ventana**: los últimos 28 días
conocidos, posteriores al fin de entrenamiento de ambos. El reto se entrena con todo lo anterior a
esa ventana. La regla está en `modelo/compuerta.py` (función pura con pruebas) y promueve solo si
se cumplen, en orden:

1. el reto produjo métricas válidas en la ventana;
2. la ventana tiene al menos 14 días;
3. el reto cuesta menos que el baseline en la ventana;
4. no hay vigente, o el reto reduce el costo del vigente en al menos **1 %**
   (`MEJORA_MINIMA=0.01`).

La métrica de comparación es el **costo de negocio** de `costos.csv` con la cantidad sugerida de
cada modelo, no el error del pronóstico. Si se promueve, `@champion` pasa al reto y el anterior
queda en `@anterior`. Si no, la versión queda registrada con `decision: descartado` y el motivo.
Un fallo en cualquier tarea no toca el alias, y la API carga el nuevo `@champion` en menos de
30 segundos sin reinicio.

### Alternativas consideradas

| Alternativa | Por qué se descartó |
|---|---|
| Promover siempre el modelo más reciente | Cambia de modelo por ruido y puede empeorar el costo sin que nadie lo note. |
| Comparar con el RMSE o el WAPE | El producto se juzga por el costo de sus sugerencias; un modelo con menor error puede tener peor costo si se equivoca en las familias caras. |
| Reentrenar con la ventana incluida y comparar la validación de cada modelo | Cada modelo se mediría en días distintos y la comparación no sería justa. |
| No exigir mejora mínima (cualquier mejora promueve) | Diferencias de décimas de punto son ruido de la ventana. |
| Mejora mínima mayor (5 %) | En el ensayo las mejoras reales fueron de 1.2 % a 3.2 %; con 5 % el modelo nunca se actualizaría aunque cambie la demanda. |
| No comparar con el baseline | Un reto podría superar a un vigente malo sin aportar nada sobre una regla simple. |

### Justificación

Comparar en la misma ventana, con la misma métrica de negocio, es la única forma justa de decidir
entre dos modelos. El umbral de 1 % evita cambios por ruido sin impedir que el modelo se adapte.
En `evidencia/RESUMEN.md` se ve la regla funcionando: versiones promovidas (4 y 6), descartadas
por mejora menor que 1 % (3 y 5) y un reentrenamiento fallido que no cambió el vigente.

---

## 5. Arquitectura y operación

| Decisión | Elegida | Alternativa | Por qué |
|---|---|---|---|
| Dónde vive el modelo | Se descarga del Registry y se guarda en un volumen de caché | Dentro de la imagen | La compuerta decide la versión sin reconstruir imágenes; con la caché, la API arranca aunque MLflow no esté. |
| Cambio de modelo | Un hilo consulta `@champion` cada 30 s y cambia en caliente | Reiniciar el contenedor | Requisito: sin reinicio manual, en menos de 2 minutos. |
| Salud | Un monitor mide base, MLflow y Airflow cada 10 s; `/health` responde con la última medición | Medir en cada llamada | `/health` nunca espera a una dependencia caída; detecta caídas y regresos en segundos. |
| Bases | PostgreSQL del producto y PostgreSQL de Airflow separados; MLflow con SQLite en su volumen | Una sola base | Lo exige el enunciado; aísla fallos. |
| Primer modelo | Servicio `inicializador` que termina antes de que arranque la API | Entrenar dentro de la API | Separa responsabilidades; si ya hay `@champion`, termina en segundos sin repetir trabajo. |
| Disparo del DAG | API REST v2 de Airflow con token JWT (FAB) | Ejecutar `airflow dags trigger` | La API no necesita Airflow instalado. |
| Serialización | Pickler de C y pyfunc como código | joblib y cloudpickle | `dill`, que Airflow importa, altera el Pickler de Python puro que usa joblib; el modelo entrenado en Airflow no cargaba en la API. Hay una prueba que lo verifica. |
| Ejecutor de Airflow | LocalExecutor | Celery | Un solo DAG sin paralelismo masivo; menos servicios y memoria. |
| Código en Airflow | Copiado en la imagen | Montado desde la laptop | La versión que corre es la del tag; evita problemas de permisos en WSL. |
| Datos publicados | Carpeta `./datos` montada en solo lectura | Copiarlos a la imagen | Los datos no deben formar parte de las imágenes ni del repositorio. |
| Archivo de contexto del agente | `AGENTS.md` | `CLAUDE.md` | Formato abierto que leen varios agentes de programación (Claude Code, Codex, OpenCode). |
