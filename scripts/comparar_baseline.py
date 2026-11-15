"""Costo que habrían tenido el baseline y el modelo inicial, sin reentrenar, en el periodo simulado.

Sirve de referencia para la simulación: mismos días y mismos costos, pero sin solicitudes
defectuosas ni reentrenamientos.

    python scripts/comparar_baseline.py --datos datos --fin-entrenamiento 2025-12-03 \
        --desde 2026-01-01 --hasta 2026-02-28 --salida evidencia/simulacion/comparacion_baseline.json
"""

from __future__ import annotations

import argparse
import json
from datetime import date
from pathlib import Path

import pandas as pd

from novamercado.catalogos import leer_catalogos
from novamercado.modelo.entrenamiento import entrenar, evaluar, tabla_entrenamiento


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--datos", type=Path, default=Path("datos"))
    p.add_argument("--fin-entrenamiento", type=date.fromisoformat, required=True)
    p.add_argument("--desde", type=date.fromisoformat, required=True)
    p.add_argument("--hasta", type=date.fromisoformat, required=True)
    p.add_argument("--salida", type=Path, required=True)
    a = p.parse_args()
    catalogos = leer_catalogos(a.datos)
    historico = pd.read_csv(a.datos / "historico_ventas.csv", parse_dates=["fecha"])
    tabla = tabla_entrenamiento(historico, catalogos)
    resultado = {"fin_entrenamiento": str(a.fin_entrenamiento), "periodo": f"{a.desde} a {a.hasta}"}
    for tipo in ("perfil", "boosting"):
        modelo = entrenar(tipo, tabla, a.fin_entrenamiento, catalogos).modelo
        m = evaluar(modelo, tabla, a.desde, a.hasta, catalogos)
        resultado[tipo] = {k: round(v, 3) for k, v in m.items()}
    a.salida.parent.mkdir(parents=True, exist_ok=True)
    a.salida.write_text(json.dumps(resultado, indent=2, ensure_ascii=False), encoding="utf-8")
    print(json.dumps(resultado, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
