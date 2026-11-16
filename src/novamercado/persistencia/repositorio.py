"""Operaciones sobre la base del producto. Funcionan con PostgreSQL y con SQLite (pruebas)."""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from functools import lru_cache

import pandas as pd
from sqlalchemy import Engine, and_, create_engine, func, select, text, update
from sqlalchemy.dialects import postgresql, sqlite

from novamercado.contrato import ObservacionCalidad
from novamercado.persistencia import esquema as t


@lru_cache
def motor(url: str) -> Engine:
    argumentos = {"pool_pre_ping": True}
    if url.startswith("postgresql"):
        argumentos |= {"pool_size": 5, "max_overflow": 5, "connect_args": {"connect_timeout": 3}}
    return create_engine(url, **argumentos)


def crear_esquema(engine: Engine) -> None:
    t.metadata.create_all(engine)


def ping(engine: Engine) -> None:
    with engine.connect() as c:
        c.execute(text("SELECT 1"))


def _insert(engine: Engine, tabla):
    return (postgresql.insert(tabla) if engine.dialect.name == "postgresql" else sqlite.insert(tabla))


# --------------------------------------------------------------------------- metadatos
def leer_metadato(engine: Engine, clave: str) -> str | None:
    with engine.connect() as c:
        return c.execute(select(t.metadatos.c.valor).where(t.metadatos.c.clave == clave)).scalar()


def escribir_metadato(engine: Engine, clave: str, valor: str) -> None:
    stmt = _insert(engine, t.metadatos).values(clave=clave, valor=valor)
    stmt = stmt.on_conflict_do_update(index_elements=["clave"], set_={"valor": valor})
    with engine.begin() as c:
        c.execute(stmt)


# --------------------------------------------------------------------------- histórico
def cargar_historico(engine: Engine, historico: pd.DataFrame, lote: int = 5000) -> int:
    """Inserta el histórico publicado. Idempotente: ignora filas ya cargadas."""
    filas = historico[["tienda_id", "fecha", "familia_id", "ventas", "en_promocion"]].copy()
    filas["fecha"] = pd.to_datetime(filas["fecha"]).dt.date
    registros = filas.to_dict("records")
    with engine.begin() as c:
        for i in range(0, len(registros), lote):
            stmt = _insert(engine, t.historico_ventas).values(registros[i:i + lote])
            c.execute(stmt.on_conflict_do_nothing())
    return len(registros)


# --------------------------------------------------------------------------- solicitudes
def registrar_solicitud(engine: Engine, *, tipo: str, cuerpo: object, http_status: int,
                        tienda_id: int | None = None, fecha: date | None = None,
                        estado_calidad: str | None = None, detalle: str | None = None,
                        version_modelo: str | None = None,
                        observaciones: list[ObservacionCalidad] | None = None,
                        predicciones: list[dict] | None = None) -> int:
    with engine.begin() as c:
        sid = c.execute(t.solicitudes.insert().values(
            tipo=tipo, cuerpo=cuerpo if isinstance(cuerpo, (dict, list)) else {"crudo": str(cuerpo)},
            http_status=http_status, tienda_id=tienda_id, fecha=fecha,
            estado_calidad=estado_calidad, detalle=detalle, version_modelo=version_modelo,
        ).returning(t.solicitudes.c.id)).scalar_one()
        if observaciones:
            c.execute(t.correcciones.insert(), [
                {"solicitud_id": sid, "campo": o.campo, "accion": o.accion, "detalle": o.detalle}
                for o in observaciones])
        if predicciones:
            c.execute(t.predicciones.insert(), [{**p, "solicitud_id": sid} for p in predicciones])
    return int(sid)


# --------------------------------------------------------------------------- observaciones
def guardar_observaciones(engine: Engine, tienda_id: int, fecha: date, ventas: dict[str, int],
                          solicitud_id: int | None) -> tuple[int, list[tuple[str, int, int]]]:
    """Registra ventas reales de forma idempotente.

    Devuelve (registros nuevos o modificados, [(familia, valor anterior, valor nuevo)]).
    Reenviar la misma observación no cambia nada y devuelve 0."""
    if not ventas:
        return 0, []
    tabla = t.observaciones
    with engine.begin() as c:
        previos = dict(c.execute(
            select(tabla.c.familia_id, tabla.c.ventas).where(
                and_(tabla.c.tienda_id == tienda_id, tabla.c.fecha == fecha,
                     tabla.c.familia_id.in_(list(ventas))))).all())
        filas = [{"tienda_id": tienda_id, "fecha": fecha, "familia_id": f, "ventas": v,
                  "solicitud_id": solicitud_id} for f, v in ventas.items()]
        stmt = _insert(engine, tabla).values(filas)
        stmt = stmt.on_conflict_do_update(
            index_elements=["tienda_id", "fecha", "familia_id"],
            set_={"ventas": stmt.excluded.ventas, "solicitud_id": stmt.excluded.solicitud_id,
                  "actualizado_en": func.now()},
            where=tabla.c.ventas != stmt.excluded.ventas,
        ).returning(tabla.c.familia_id)
        cambiadas = [r[0] for r in c.execute(stmt).all()]
    modificadas = [(f, previos[f], ventas[f]) for f in cambiadas if f in previos]
    return len(cambiadas), modificadas


def asociar_solicitud(engine: Engine, tienda_id: int, fecha: date, familias: list[str],
                      solicitud_id: int) -> None:
    """Enlaza las observaciones nuevas o modificadas con la solicitud que las trajo."""
    if not familias:
        return
    with engine.begin() as c:
        c.execute(update(t.observaciones).where(and_(
            t.observaciones.c.tienda_id == tienda_id, t.observaciones.c.fecha == fecha,
            t.observaciones.c.familia_id.in_(familias))).values(solicitud_id=solicitud_id))


def ultima_fecha_observada(engine: Engine, tienda_id: int) -> date | None:
    with engine.connect() as c:
        obs = c.execute(select(func.max(t.observaciones.c.fecha)).where(
            t.observaciones.c.tienda_id == tienda_id)).scalar()
        hist = c.execute(select(func.max(t.historico_ventas.c.fecha)).where(
            t.historico_ventas.c.tienda_id == tienda_id)).scalar()
    fechas = [_como_fecha(d) for d in (obs, hist) if d is not None]
    return max(fechas) if fechas else None


def _como_fecha(valor) -> date:
    if isinstance(valor, datetime):
        return valor.date()
    if isinstance(valor, str):
        return date.fromisoformat(valor[:10])
    return valor


# --------------------------------------------------------------------------- ventas para modelar
def ventas_conocidas(engine: Engine, tienda_id: int | None = None, desde: date | None = None,
                     hasta: date | None = None) -> pd.DataFrame:
    """Histórico ∪ observaciones (la observación prevalece), con la promoción del día.

    La promoción de un día observado se toma de la última solicitud de predicción de ese día;
    si no existe queda vacía (el modelo admite valores faltantes)."""
    def filtro(tabla):
        cond = []
        if tienda_id is not None:
            cond.append(tabla.c.tienda_id == tienda_id)
        if desde is not None:
            cond.append(tabla.c.fecha >= desde)
        if hasta is not None:
            cond.append(tabla.c.fecha <= hasta)
        return and_(*cond) if cond else True

    h, o, p = t.historico_ventas, t.observaciones, t.predicciones
    with engine.connect() as c:
        hist = pd.DataFrame(c.execute(select(h.c.tienda_id, h.c.fecha, h.c.familia_id, h.c.ventas,
                                             h.c.en_promocion).where(filtro(h))).all(),
                            columns=["tienda_id", "fecha", "familia_id", "ventas", "en_promocion"])
        obs = pd.DataFrame(c.execute(select(o.c.tienda_id, o.c.fecha, o.c.familia_id, o.c.ventas)
                                     .where(filtro(o))).all(),
                           columns=["tienda_id", "fecha", "familia_id", "ventas"])
        ultima = (select(p.c.tienda_id, p.c.fecha, p.c.familia_id, func.max(p.c.id).label("id"))
                  .where(filtro(p)).group_by(p.c.tienda_id, p.c.fecha, p.c.familia_id).subquery())
        promos = pd.DataFrame(c.execute(select(p.c.tienda_id, p.c.fecha, p.c.familia_id, p.c.en_promocion)
                                        .join(ultima, p.c.id == ultima.c.id)).all(),
                              columns=["tienda_id", "fecha", "familia_id", "en_promocion"])
    clave = ["tienda_id", "fecha", "familia_id"]
    for df in (hist, obs, promos):
        df["fecha"] = pd.to_datetime(df["fecha"])
    if len(obs):
        obs = obs.merge(promos, on=clave, how="left")
        hist = hist.set_index(clave)
        obs = obs.set_index(clave)
        prom_hist = hist["en_promocion"].reindex(obs.index)
        obs["en_promocion"] = obs["en_promocion"].fillna(prom_hist)
        hist = hist.drop(index=hist.index.intersection(obs.index))
        datos = pd.concat([hist, obs]).reset_index()
    else:
        datos = hist
    datos["ventas"] = datos["ventas"].astype(float)
    datos["en_promocion"] = pd.to_numeric(datos["en_promocion"], errors="coerce")
    return datos.sort_values(clave).reset_index(drop=True)


def historia_para_predecir(engine: Engine, tienda_id: int, fecha: date, dias: int) -> pd.DataFrame:
    return ventas_conocidas(engine, tienda_id, fecha - timedelta(days=dias), fecha - timedelta(days=1))


# --------------------------------------------------------------------------- reentrenamientos
def crear_reentrenamiento(engine: Engine, run_id: str) -> None:
    with engine.begin() as c:
        c.execute(t.reentrenamientos.insert().values(id=run_id, estado="en_curso"))


def leer_reentrenamiento(engine: Engine, run_id: str) -> dict | None:
    with engine.connect() as c:
        fila = c.execute(select(t.reentrenamientos).where(t.reentrenamientos.c.id == run_id)).mappings().first()
    return dict(fila) if fila else None


def terminar_reentrenamiento(engine: Engine, run_id: str, *, estado: str, promovido: bool,
                             version: str | None, motivo: str, detalle: dict | None = None) -> None:
    """Escribe el resultado final. Crea la fila si el DAG se disparó desde Airflow."""
    valores = {"estado": estado, "promovido": promovido, "version": version, "motivo": motivo,
               "detalle": detalle, "terminado_en": datetime.now(UTC)}
    stmt = _insert(engine, t.reentrenamientos).values(id=run_id, **valores)
    stmt = stmt.on_conflict_do_update(index_elements=["id"], set_=valores)
    with engine.begin() as c:
        c.execute(stmt)
