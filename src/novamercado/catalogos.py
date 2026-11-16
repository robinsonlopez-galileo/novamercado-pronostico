"""Catálogos publicados: tiendas, familias, costos y feriados."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from functools import lru_cache
from pathlib import Path

import pandas as pd

ARCHIVOS = ["tiendas.csv", "familias.csv", "costos.csv", "feriados.csv", "historico_ventas.csv"]


class DatosFaltantes(RuntimeError):
    """Faltan archivos publicados en la carpeta de datos."""


def verificar_archivos(directorio: Path) -> None:
    faltan = [a for a in ARCHIVOS if not (directorio / a).exists()]
    if faltan:
        raise DatosFaltantes(
            f"Faltan archivos en {directorio}: {', '.join(faltan)}. "
            "Coloque los archivos publicados en esa carpeta (ver README.md)."
        )


@dataclass(frozen=True)
class Catalogos:
    tiendas: pd.DataFrame  # índice tienda_id
    familias: pd.DataFrame  # columnas familia_id, nombre
    costos: pd.DataFrame  # índice familia_id; costo_faltante, costo_sobrante
    feriados: pd.DataFrame  # fecha, nombre, tipo, ambito

    @property
    def familia_ids(self) -> list[str]:
        return list(self.familias["familia_id"])

    @property
    def tienda_ids(self) -> list[int]:
        return [int(t) for t in self.tiendas.index]

    @property
    def tipos_tienda(self) -> list[str]:
        return sorted(self.tiendas["tipo"].unique())

    @property
    def fin_calendario(self) -> date:
        return self.feriados["fecha"].max().date()

    def apertura(self, tienda_id: int) -> date:
        return self.tiendas.loc[tienda_id, "fecha_apertura"].date()

    def ciudad(self, tienda_id: int) -> str:
        return str(self.tiendas.loc[tienda_id, "ciudad"])

    def cuantil_optimo(self, familia_id: str) -> float:
        """Cuantil que minimiza el costo esperado (problema del vendedor de periódicos)."""
        c = self.costos.loc[familia_id]
        return float(c.costo_faltante / (c.costo_faltante + c.costo_sobrante))


def leer_catalogos(directorio: Path) -> Catalogos:
    tiendas = pd.read_csv(directorio / "tiendas.csv", parse_dates=["fecha_apertura"])
    tiendas["tienda_id"] = tiendas["tienda_id"].astype(int)
    familias = pd.read_csv(directorio / "familias.csv", dtype=str)
    costos = pd.read_csv(directorio / "costos.csv").set_index("familia_id")
    feriados = pd.read_csv(directorio / "feriados.csv", parse_dates=["fecha"])
    faltan_costos = set(familias["familia_id"]) - set(costos.index)
    if faltan_costos:
        raise DatosFaltantes(f"costos.csv no tiene costos para: {sorted(faltan_costos)}")
    return Catalogos(tiendas.set_index("tienda_id"), familias, costos, feriados)


@lru_cache
def cargar(directorio: str) -> Catalogos:
    return leer_catalogos(Path(directorio))
