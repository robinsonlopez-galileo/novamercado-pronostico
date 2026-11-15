"""Defensa del contrato: interpreta solicitudes crudas y aplica la política de cada problema.

Cada problema recibe una de tres políticas (ver DECISIONES.md):

- reparar: la corrección es inequívoca; se informa con accion="reparar".
- advertir: se responde con un supuesto explícito; se informa con accion="advertir".
- rechazar: se lanza `Rechazo`, que la API convierte en 422 con `detail`.
"""

from novamercado.limpieza.base import Rechazo, Registro
from novamercado.limpieza.solicitudes import (
    ObservacionLimpia,
    PrediccionLimpia,
    preparar_observacion,
    preparar_prediccion,
)

__all__ = [
    "ObservacionLimpia",
    "PrediccionLimpia",
    "Rechazo",
    "Registro",
    "preparar_observacion",
    "preparar_prediccion",
]
