"""Piezas comunes de la limpieza: el registro de acciones y el rechazo."""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field

from novamercado.contrato import ObservacionCalidad


class Rechazo(Exception):
    """La solicitud no se puede atender sin inventar datos: se responde 422."""

    def __init__(self, detalle: str, campo: str | None = None):
        self.detalle = f"{campo}: {detalle}" if campo else detalle
        super().__init__(self.detalle)


@dataclass
class Registro:
    """Acumula lo que la limpieza hizo con una solicitud, en el formato del contrato."""

    observaciones: list[ObservacionCalidad] = field(default_factory=list)

    def reparar(self, campo: str, detalle: str) -> None:
        self.observaciones.append(ObservacionCalidad(campo=campo, accion="reparar", detalle=detalle))

    def advertir(self, campo: str, detalle: str) -> None:
        self.observaciones.append(ObservacionCalidad(campo=campo, accion="advertir", detalle=detalle))


def sin_acentos(texto: str) -> str:
    descompuesto = unicodedata.normalize("NFKD", texto)
    return "".join(c for c in descompuesto if not unicodedata.combining(c))


def clave(texto: str) -> str:
    """Forma comparable de un nombre: sin acentos, minúsculas y solo letras y dígitos."""
    return re.sub(r"[^a-z0-9]", "", sin_acentos(str(texto)).lower())


def mostrar(valor: object) -> str:
    """Representación corta de un valor para los mensajes."""
    texto = repr(valor) if isinstance(valor, str) else str(valor)
    return texto if len(texto) <= 60 else texto[:57] + "..."
