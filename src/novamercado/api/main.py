"""API de NovaMercado (contrato del Anexo del enunciado).

Los endpoints solo orquestan: la limpieza vive en `novamercado.limpieza`, las variables en
`novamercado.features`, el modelo en `novamercado.modelo` y el registro en
`novamercado.persistencia`.
"""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from datetime import date, timedelta
from typing import Any

from fastapi import Body, FastAPI, Request
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from novamercado import catalogos as cat
from novamercado import configuracion
from novamercado.contrato import (
    Calidad,
    EstadoReentrenamiento,
    ModeloVigente,
    ObservacionCalidad,
    RespuestaDisparo,
    RespuestaObservacion,
    RespuestaPrediccion,
    Salud,
)
from novamercado.limpieza import Rechazo, preparar_observacion, preparar_prediccion
from novamercado.persistencia import repositorio as repo
from novamercado.servicio import predictor
from novamercado.servicio.airflow_cliente import ESTADOS, AirflowNoDisponible, ClienteAirflow
from novamercado.servicio.gestor_modelo import GestorModelo
from novamercado.servicio.salud import MonitorSalud

log = logging.getLogger("api")

EJEMPLO_PREDICCION = {"tienda_id": 5, "fecha": "2025-11-17", "familias": [
    {"familia_id": "abarrotes", "en_promocion": 0}, {"familia_id": "bebidas", "en_promocion": 8}]}
EJEMPLO_OBSERVACION = {"tienda_id": 5, "fecha": "2025-11-17", "ventas": [
    {"familia_id": "abarrotes", "ventas": 994}, {"familia_id": "bebidas", "ventas": 1292}]}


def _error(status: int, detalle: str) -> JSONResponse:
    return JSONResponse(status_code=status, content={"detail": detalle})


def crear_app(cfg: configuracion.Configuracion | None = None, *, gestor: GestorModelo | None = None,
              monitor: MonitorSalud | None = None, airflow: ClienteAirflow | None = None,
              iniciar_hilos: bool = True) -> FastAPI:
    cfg = cfg or configuracion.obtener()
    gestor = gestor or GestorModelo(cfg)
    monitor = monitor or MonitorSalud(cfg)
    airflow = airflow or ClienteAirflow(cfg)

    @asynccontextmanager
    async def ciclo_de_vida(app: FastAPI):
        cat.verificar_archivos(cfg.dir_datos)
        try:
            repo.crear_esquema(repo.motor(cfg.db_url))
        except Exception as e:  # noqa: BLE001 - la salud lo reportará
            log.warning("No se pudo verificar el esquema: %s", e)
        if iniciar_hilos:
            gestor.iniciar()
            monitor.iniciar()
        yield
        gestor.detener()
        monitor.detener()

    app = FastAPI(title="NovaMercado · Pronóstico diario de ventas", version="2.0.0",
                  lifespan=ciclo_de_vida)
    app.state.gestor, app.state.monitor, app.state.airflow = gestor, monitor, airflow

    def catalogos():
        return cat.cargar(str(cfg.dir_datos))

    def engine():
        return repo.motor(cfg.db_url)

    def referencia(tienda: int) -> date | None:
        """Día siguiente a la última venta conocida de la tienda (calendario de operación)."""
        try:
            ultima = repo.ultima_fecha_observada(engine(), tienda)
        except Exception:  # noqa: BLE001
            return None
        return ultima + timedelta(days=1) if ultima else None

    def registrar_rechazo(tipo: str, cuerpo: Any, detalle: str) -> None:
        try:
            repo.registrar_solicitud(engine(), tipo=tipo, cuerpo=cuerpo, http_status=422, detalle=detalle)
        except Exception as e:  # noqa: BLE001
            log.warning("No se pudo registrar el rechazo: %s", e)

    @app.exception_handler(RequestValidationError)
    async def json_invalido(request: Request, exc: RequestValidationError):
        primero = exc.errors()[0] if exc.errors() else {"msg": "solicitud inválida"}
        detalle = f"el cuerpo no es JSON válido o no tiene la forma esperada: {primero.get('msg')}"
        tipo = "observacion" if "observaciones" in request.url.path else "prediccion"
        if request.url.path.startswith("/v1/"):
            cuerpo = (await request.body()).decode("utf-8", "replace")[:5000]
            registrar_rechazo(tipo, {"crudo": cuerpo}, detalle)
        return _error(422, detalle)

    # ------------------------------------------------------------------ predicción
    @app.post("/v1/prediccion", response_model=RespuestaPrediccion)
    def prediccion(cuerpo: Any = Body(..., openapi_examples={"valida": {"value": EJEMPLO_PREDICCION}})):
        cargado = gestor.actual
        if cargado is None:
            return _error(503, "el servicio aún no tiene un modelo cargado")
        try:
            limpia = preparar_prediccion(cuerpo, catalogos(), referencia)
        except Rechazo as e:
            registrar_rechazo("prediccion", cuerpo, e.detalle)
            return _error(422, e.detalle)
        solicitud = limpia.solicitud
        observaciones = list(limpia.observaciones)
        try:
            predicciones, con_historia = predictor.predecir(solicitud, cargado.modelo, catalogos(), engine())
        except Exception as e:  # noqa: BLE001
            log.exception("Fallo al predecir")
            return _error(503, f"no se pudo leer la historia de ventas: {str(e).splitlines()[0][:150]}")
        if not con_historia:
            observaciones.append(ObservacionCalidad(
                campo="fecha", accion="advertir",
                detalle="no hay ventas registradas de la tienda en los 28 días previos; el "
                        "pronóstico se apoya en patrones generales de la tienda y la familia"))
        respuesta = RespuestaPrediccion(tienda_id=solicitud.tienda_id, fecha=solicitud.fecha,
                                        version_modelo=cargado.version, predicciones=predicciones,
                                        calidad=Calidad.desde(observaciones))
        promo = {f.familia_id: f.en_promocion for f in solicitud.familias}
        try:
            repo.registrar_solicitud(
                engine(), tipo="prediccion", cuerpo=cuerpo, http_status=200,
                tienda_id=solicitud.tienda_id, fecha=solicitud.fecha,
                estado_calidad=respuesta.calidad.estado, version_modelo=cargado.version,
                observaciones=observaciones,
                predicciones=[{"tienda_id": solicitud.tienda_id, "fecha": solicitud.fecha,
                               "familia_id": p.familia_id, "en_promocion": promo[p.familia_id],
                               "venta_esperada": p.venta_esperada, "cantidad_sugerida": p.cantidad_sugerida,
                               "version_modelo": cargado.version} for p in predicciones])
        except Exception:  # noqa: BLE001
            log.exception("No se pudo registrar la predicción")
            return _error(503, "no se pudo registrar la predicción en la base de datos")
        return respuesta

    # ------------------------------------------------------------------ observaciones
    @app.post("/v1/observaciones", response_model=RespuestaObservacion)
    def observaciones(cuerpo: Any = Body(..., openapi_examples={"valida": {"value": EJEMPLO_OBSERVACION}})):
        try:
            limpia = preparar_observacion(cuerpo, catalogos(), referencia)
        except Rechazo as e:
            registrar_rechazo("observacion", cuerpo, e.detalle)
            return _error(422, e.detalle)
        s = limpia.solicitud
        ventas = {v.familia_id: v.ventas for v in s.ventas}
        obs = list(limpia.observaciones)
        try:
            guardados, modificadas = repo.guardar_observaciones(engine(), s.tienda_id, s.fecha, ventas, None)
        except Exception as e:  # noqa: BLE001
            log.exception("No se pudieron guardar las observaciones")
            return _error(503, f"no se pudo guardar en la base de datos: {str(e).splitlines()[0][:150]}")
        for familia, antes, despues in modificadas:
            obs.append(ObservacionCalidad(
                campo=f"ventas.{familia}", accion="advertir",
                detalle=f"ya había ventas registradas para {familia} ({antes}); se reemplazaron por {despues}"))
        respuesta = RespuestaObservacion(registros_guardados=guardados, calidad=Calidad.desde(obs))
        try:
            sid = repo.registrar_solicitud(engine(), tipo="observacion", cuerpo=cuerpo, http_status=200,
                                           tienda_id=s.tienda_id, fecha=s.fecha,
                                           estado_calidad=respuesta.calidad.estado, observaciones=obs)
            repo.asociar_solicitud(engine(), s.tienda_id, s.fecha,
                                   [f for f in ventas if guardados], sid)
        except Exception:  # noqa: BLE001
            log.exception("No se pudo registrar la solicitud de observación")
        return respuesta

    # ------------------------------------------------------------------ administración
    @app.post("/admin/reentrenar", status_code=202, response_model=RespuestaDisparo)
    def reentrenar():
        try:
            run_id = airflow.disparar()
        except AirflowNoDisponible as e:
            return _error(503, str(e))
        try:
            repo.crear_reentrenamiento(engine(), run_id)
        except Exception:  # noqa: BLE001
            log.exception("No se pudo registrar el reentrenamiento %s", run_id)
        return RespuestaDisparo(id=run_id)

    @app.get("/admin/reentrenar/{run_id}", response_model=EstadoReentrenamiento,
             response_model_exclude_none=True)
    def estado_reentrenamiento(run_id: str):
        try:
            fila = repo.leer_reentrenamiento(engine(), run_id)
        except Exception as e:  # noqa: BLE001
            return _error(503, f"base de datos no disponible: {e}")
        estado_airflow = None
        try:
            estado_airflow = airflow.estado(run_id)
        except Exception:  # noqa: BLE001 - sin Airflow se responde con lo registrado
            pass
        if fila is None and estado_airflow is None:
            return _error(404, f"no existe la ejecución {run_id}")
        if fila is not None and fila["estado"] in ("exitoso", "fallido"):
            return EstadoReentrenamiento(estado=fila["estado"], promovido=fila["promovido"],
                                         version=fila["version"], motivo=fila["motivo"])
        estado = ESTADOS.get(estado_airflow or "", "en_curso")
        if estado == "en_curso":
            return EstadoReentrenamiento(estado="en_curso")
        vigente = gestor.actual.version if gestor.actual else None
        if estado == "exitoso":  # terminó, pero el resultado aún no estaba escrito
            return EstadoReentrenamiento(estado="exitoso", promovido=False, version=vigente,
                                         motivo="La ejecución terminó sin registrar resultado; se conserva el vigente")
        tarea = None
        try:
            tarea = airflow.tarea_fallida(run_id)
        except Exception:  # noqa: BLE001
            pass
        motivo = (f"La ejecución falló en la tarea {tarea}" if tarea else "La ejecución falló") + \
                 "; el modelo vigente no cambió"
        try:
            repo.terminar_reentrenamiento(engine(), run_id, estado="fallido", promovido=False,
                                          version=vigente, motivo=motivo)
        except Exception:  # noqa: BLE001
            pass
        return EstadoReentrenamiento(estado="fallido", promovido=False, version=vigente, motivo=motivo)

    # ------------------------------------------------------------------ modelo y salud
    @app.get("/modelo", response_model=ModeloVigente)
    def modelo():
        cargado = gestor.actual
        if cargado is None:
            return _error(503, "el servicio aún no tiene un modelo cargado")
        return ModeloVigente(nombre=cargado.nombre, alias=cargado.alias, version=cargado.version)

    @app.get("/health", response_model=Salud, response_model_exclude_none=True)
    def salud():
        estado = monitor.estado
        cargado = gestor.actual
        detalle = {"modelo_cargado": cargado is not None,
                   "version_modelo": cargado.version if cargado else None,
                   "dependencias": estado.disponibles}
        if cargado is None:
            return JSONResponse(status_code=503, content=jsonable_encoder(
                {"estado": "iniciando", "motivo": "todavía no hay un modelo cargado", **detalle}))
        if not estado.medido:
            return Salud(estado="ok", **detalle)
        caidas = [n for n, ok in estado.disponibles.items() if not ok]
        if caidas:
            motivo = "; ".join(f"{n} no disponible ({estado.errores.get(n, '')})" for n in caidas)
            return Salud(estado="degradado", motivo=motivo, **detalle)
        return Salud(estado="ok", **detalle)

    return app


def app() -> FastAPI:
    """Fábrica para uvicorn: `uvicorn novamercado.api.main:app --factory`."""
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    return crear_app()
