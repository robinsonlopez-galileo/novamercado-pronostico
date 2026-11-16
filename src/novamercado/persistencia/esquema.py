"""Tablas del producto. Base propia, separada de la de Airflow y del backend de MLflow."""

from __future__ import annotations

from sqlalchemy import (
                        JSON,
                        BigInteger,
                        Boolean,
                        Column,
                        Date,
                        DateTime,
                        Float,
                        ForeignKey,
                        Index,
                        Integer,
                        MetaData,
                        String,
                        Table,
                        Text,
                        func,
)

metadata = MetaData()

# Histórico publicado (se carga una vez desde historico_ventas.csv).
historico_ventas = Table(
    "historico_ventas", metadata,
    Column("tienda_id", Integer, primary_key=True),
    Column("fecha", Date, primary_key=True),
    Column("familia_id", String(40), primary_key=True),
    Column("ventas", Integer, nullable=False),
    Column("en_promocion", Integer, nullable=True),
)

# Cada solicitud recibida, también las rechazadas, con su cuerpo original.
solicitudes = Table(
    "solicitudes", metadata,
    Column("id", BigInteger().with_variant(Integer, "sqlite"), primary_key=True, autoincrement=True),
    Column("tipo", String(20), nullable=False),  # prediccion | observacion
    Column("recibido_en", DateTime(timezone=True), server_default=func.now(), nullable=False),
    Column("cuerpo", JSON, nullable=True),
    Column("tienda_id", Integer, nullable=True),
    Column("fecha", Date, nullable=True),
    Column("http_status", Integer, nullable=False),
    Column("estado_calidad", String(20), nullable=True),
    Column("detalle", Text, nullable=True),
    Column("version_modelo", String(20), nullable=True),
)

# Correcciones y advertencias aplicadas a cada solicitud (calidad.observaciones).
correcciones = Table(
    "correcciones", metadata,
    Column("id", BigInteger().with_variant(Integer, "sqlite"), primary_key=True, autoincrement=True),
    Column("solicitud_id", BigInteger().with_variant(Integer, "sqlite"), ForeignKey("solicitudes.id"), nullable=False),
    Column("campo", Text, nullable=False),
    Column("accion", String(10), nullable=False),
    Column("detalle", Text, nullable=False),
)

# Cada predicción emitida, con la versión del modelo que la produjo.
predicciones = Table(
    "predicciones", metadata,
    Column("id", BigInteger().with_variant(Integer, "sqlite"), primary_key=True, autoincrement=True),
    Column("solicitud_id", BigInteger().with_variant(Integer, "sqlite"), ForeignKey("solicitudes.id"), nullable=False),
    Column("tienda_id", Integer, nullable=False),
    Column("fecha", Date, nullable=False),
    Column("familia_id", String(40), nullable=False),
    Column("en_promocion", Integer, nullable=False),
    Column("venta_esperada", Float, nullable=False),
    Column("cantidad_sugerida", Integer, nullable=False),
    Column("version_modelo", String(20), nullable=False),
    Column("creado_en", DateTime(timezone=True), server_default=func.now(), nullable=False),
)
Index("ix_predicciones_clave", predicciones.c.tienda_id, predicciones.c.fecha, predicciones.c.familia_id)

# Ventas reales observadas: una fila por tienda, fecha y familia (registro idempotente).
observaciones = Table(
    "observaciones", metadata,
    Column("tienda_id", Integer, primary_key=True),
    Column("fecha", Date, primary_key=True),
    Column("familia_id", String(40), primary_key=True),
    Column("ventas", Integer, nullable=False),
    Column("solicitud_id", BigInteger().with_variant(Integer, "sqlite"), nullable=True),
    Column("actualizado_en", DateTime(timezone=True), server_default=func.now(), onupdate=func.now()),
)

# Ejecuciones de reentrenamiento pedidas por /admin/reentrenar.
reentrenamientos = Table(
    "reentrenamientos", metadata,
    Column("id", String(250), primary_key=True),  # dag_run_id de Airflow
    Column("solicitado_en", DateTime(timezone=True), server_default=func.now(), nullable=False),
    Column("estado", String(20), nullable=False),  # en_curso | exitoso | fallido
    Column("promovido", Boolean, nullable=True),
    Column("version", String(20), nullable=True),
    Column("motivo", Text, nullable=True),
    Column("detalle", JSON, nullable=True),
    Column("terminado_en", DateTime(timezone=True), nullable=True),
)

# Marcas de inicialización (por ejemplo, que el histórico ya se cargó).
metadatos = Table(
    "metadatos", metadata,
    Column("clave", String(80), primary_key=True),
    Column("valor", Text, nullable=False),
)
