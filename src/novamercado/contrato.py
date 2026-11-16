"""Contrato del servicio (Anexo del enunciado) como modelos de Pydantic.

Las solicitudes entran crudas y pasan por `novamercado.limpieza`; el resultado de la limpieza
se valida aquí en modo estricto. Si algo no cumple el contrato después de limpiar, la solicitud
se rechaza con 422. Las respuestas también se construyen con estos modelos, de modo que nunca
se omite ni se renombra un campo del contrato.
"""

from __future__ import annotations

from datetime import date
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, NonNegativeInt, PositiveInt

Accion = Literal["reparar", "advertir"]
EstadoCalidad = Literal["ok", "corregido", "advertencia"]


class _Estricto(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid")


# --------------------------------------------------------------------------- solicitudes limpias
class FamiliaPromocion(_Estricto):
    familia_id: str = Field(min_length=1)
    en_promocion: NonNegativeInt


class SolicitudPrediccion(_Estricto):
    tienda_id: PositiveInt
    fecha: date
    familias: list[FamiliaPromocion] = Field(min_length=1)


class VentaFamilia(_Estricto):
    familia_id: str = Field(min_length=1)
    ventas: NonNegativeInt


class SolicitudObservacion(_Estricto):
    tienda_id: PositiveInt
    fecha: date
    ventas: list[VentaFamilia]


# --------------------------------------------------------------------------- respuestas
class ObservacionCalidad(BaseModel):
    campo: str
    accion: Accion
    detalle: str


class Calidad(BaseModel):
    estado: EstadoCalidad
    observaciones: list[ObservacionCalidad] = []

    @classmethod
    def desde(cls, observaciones: list[ObservacionCalidad]) -> Calidad:
        if not observaciones:
            return cls(estado="ok", observaciones=[])
        estado = "advertencia" if any(o.accion == "advertir" for o in observaciones) else "corregido"
        return cls(estado=estado, observaciones=observaciones)


class PrediccionFamilia(BaseModel):
    familia_id: str
    venta_esperada: float
    cantidad_sugerida: NonNegativeInt


class RespuestaPrediccion(BaseModel):
    tienda_id: int
    fecha: date
    version_modelo: str
    predicciones: list[PrediccionFamilia]
    calidad: Calidad


class RespuestaObservacion(BaseModel):
    registros_guardados: NonNegativeInt
    calidad: Calidad


class RespuestaDisparo(BaseModel):
    id: str


class EstadoReentrenamiento(BaseModel):
    model_config = ConfigDict(extra="allow")
    estado: Literal["en_curso", "exitoso", "fallido"]
    promovido: bool | None = None
    version: str | None = None
    motivo: str | None = None


class ModeloVigente(BaseModel):
    nombre: str
    alias: str
    version: str


class Salud(BaseModel):
    model_config = ConfigDict(extra="allow")
    estado: Literal["ok", "degradado", "iniciando"]
    motivo: str | None = None
