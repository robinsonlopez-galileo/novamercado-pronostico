"""Métrica de negocio (costos.csv) y elección de la cantidad sugerida.

costo = c_faltante · máx(real − sugerido, 0) + c_sobrante · máx(sugerido − real, 0)

La cantidad sugerida es venta_esperada × factor de la familia, redondeada hacia arriba. El
factor se elige en datos que el modelo no usó para ajustarse, minimizando ese mismo costo. Es
la versión empírica del problema del vendedor de periódicos: con faltantes caros (licores) el
factor sube; con sobrantes caros (panadería) baja.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from novamercado.catalogos import Catalogos

FACTORES = np.round(np.arange(0.50, 2.001, 0.01), 2)


def cantidad_sugerida(venta_esperada: np.ndarray | pd.Series, factor: np.ndarray | pd.Series) -> np.ndarray:
    """Entero no negativo: ceil(venta_esperada × factor)."""
    x = np.asarray(venta_esperada, dtype=float) * np.asarray(factor, dtype=float)
    x = np.where(np.isfinite(x), x, 0.0)
    return np.ceil(np.clip(x, 0, None) - 1e-9).astype(int)


def costo_filas(real: np.ndarray, sugerido: np.ndarray, c_faltante: np.ndarray,
                c_sobrante: np.ndarray) -> np.ndarray:
    real = np.asarray(real, dtype=float)
    sugerido = np.asarray(sugerido, dtype=float)
    return (np.asarray(c_faltante) * np.clip(real - sugerido, 0, None)
            + np.asarray(c_sobrante) * np.clip(sugerido - real, 0, None))


def costos_por_fila(familias: pd.Series, catalogos: Catalogos) -> tuple[np.ndarray, np.ndarray]:
    c = catalogos.costos
    return (familias.map(c["costo_faltante"]).to_numpy(float),
            familias.map(c["costo_sobrante"]).to_numpy(float))


def costo_total(df: pd.DataFrame, catalogos: Catalogos, col_sugerido: str = "cantidad_sugerida") -> float:
    """Costo total de un DataFrame con familia_id, ventas reales y cantidad sugerida."""
    cf, cs = costos_por_fila(df["familia_id"], catalogos)
    return float(costo_filas(df["ventas"], df[col_sugerido], cf, cs).sum())


def elegir_factores(df: pd.DataFrame, catalogos: Catalogos) -> dict[str, float]:
    """Factor por familia que minimiza el costo en `df` (familia_id, ventas, venta_esperada)."""
    factores: dict[str, float] = {}
    for familia in catalogos.familia_ids:
        sub = df[df["familia_id"] == familia]
        if sub.empty:
            factores[familia] = 1.0
            continue
        cf = catalogos.costos.loc[familia, "costo_faltante"]
        cs = catalogos.costos.loc[familia, "costo_sobrante"]
        pred = sub["venta_esperada"].to_numpy(float)[:, None]
        real = sub["ventas"].to_numpy(float)[:, None]
        sug = np.ceil(np.clip(pred * FACTORES[None, :], 0, None) - 1e-9)
        costo = (cf * np.clip(real - sug, 0, None) + cs * np.clip(sug - real, 0, None)).sum(axis=0)
        factores[familia] = float(FACTORES[int(np.argmin(costo))])
    return factores


def metricas(df: pd.DataFrame, catalogos: Catalogos) -> dict[str, float]:
    """Métricas técnicas y de negocio sobre df con ventas, venta_esperada y cantidad_sugerida."""
    real = df["ventas"].to_numpy(float)
    pred = df["venta_esperada"].to_numpy(float)
    error = pred - real
    return {
        "costo": costo_total(df, catalogos),
        "costo_por_registro": costo_total(df, catalogos) / max(len(df), 1),
        "mae": float(np.mean(np.abs(error))),
        "rmse": float(np.sqrt(np.mean(error ** 2))),
        "wape": float(np.abs(error).sum() / max(real.sum(), 1.0)),
        "sesgo": float(error.sum() / max(real.sum(), 1.0)),
        "n": float(len(df)),
    }
