"""Criterio de reemplazo del modelo vigente. Función pura, sin MLflow: se prueba con pytest.

Ambos modelos se evalúan en la misma ventana de días, posterior al fin de entrenamiento de los
dos, con el mismo código de costo y los mismos costos.csv. Reglas, en orden:

1. El reto produjo métricas válidas sobre la ventana.
2. La ventana tiene al menos DIAS_MINIMOS días: una comparación más corta no es confiable.
3. El reto cuesta menos que el baseline en esa ventana (si no, no aporta sobre lo simple).
4. Si no hay modelo vigente, se promueve.
5. El reto reduce el costo del vigente al menos en `mejora_minima` (1 % por defecto), para no
   cambiar de modelo por ruido.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

DIAS_MINIMOS = 14


@dataclass(frozen=True)
class Decision:
    promover: bool
    motivo: str


def _q(x: float) -> str:
    return f"{x:,.0f}".replace(",", " ")


def decidir(costo_reto: float | None, costo_vigente: float | None, costo_baseline: float | None,
            dias_ventana: int, mejora_minima: float = 0.01) -> Decision:
    if costo_reto is None or not math.isfinite(costo_reto):
        return Decision(False, "El modelo nuevo no produjo métricas válidas en la ventana de evaluación")
    if dias_ventana < DIAS_MINIMOS:
        return Decision(False, f"Ventana de evaluación de {dias_ventana} días, menor que el mínimo "
                               f"de {DIAS_MINIMOS}; se conserva el vigente")
    if costo_baseline is not None and costo_reto >= costo_baseline:
        return Decision(False, f"Costo en validación {_q(costo_reto)} no mejora al baseline "
                               f"({_q(costo_baseline)})")
    if costo_vigente is None or not math.isfinite(costo_vigente):
        return Decision(True, f"Costo en validación {_q(costo_reto)}; no había modelo vigente comparable")
    umbral = costo_vigente * (1 - mejora_minima)
    if costo_reto <= umbral:
        return Decision(True, f"Costo en validación {_q(costo_reto)} vs {_q(costo_vigente)} del vigente")
    return Decision(False, f"Costo en validación {_q(costo_reto)} vs {_q(costo_vigente)} del vigente: "
                           f"mejora menor que {mejora_minima:.0%}")
