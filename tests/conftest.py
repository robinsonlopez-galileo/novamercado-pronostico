"""Fixtures. Las pruebas no necesitan MLflow, Airflow, Docker ni los datos publicados: usan un
catálogo mínimo y datos sintéticos en una carpeta temporal y SQLite como base."""

from __future__ import annotations

from datetime import date, timedelta
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from novamercado import catalogos as cat
from novamercado.configuracion import Configuracion

FAMILIAS = [("abarrotes", "Abarrotes"), ("bebidas", "Bebidas"), ("lacteos", "Lácteos"),
            ("panaderia", "Panadería"), ("frutas_verduras", "Frutas y verduras"),
            ("snacks", "Snacks y dulces")]


def escribir_datos(directorio: Path, dias: int = 120, fin: date = date(2026, 2, 28)) -> Path:
    directorio.mkdir(parents=True, exist_ok=True)
    pd.DataFrame({
        "tienda_id": [1, 5, 10], "nombre": ["Z10", "Xela", "Z16"],
        "ciudad": ["Guatemala", "Quetzaltenango", "Guatemala"],
        "departamento": ["Guatemala", "Quetzaltenango", "Guatemala"],
        "tipo": ["hipermercado", "hipermercado", "express"],
        "fecha_apertura": ["2019-01-01", "2019-01-01", "2025-12-15"],
    }).to_csv(directorio / "tiendas.csv", index=False)
    pd.DataFrame(FAMILIAS, columns=["familia_id", "nombre"]).to_csv(directorio / "familias.csv", index=False)
    pd.DataFrame({"familia_id": [f for f, _ in FAMILIAS], "costo_faltante": [1.0, 1.0, 1.0, 1.0, 1.0, 1.0],
                  "costo_sobrante": [0.2, 0.2, 1.2, 2.5, 2.0, 0.3]}).to_csv(directorio / "costos.csv", index=False)
    pd.DataFrame({"fecha": ["2025-12-25", "2026-01-01", "2026-02-14", "2026-12-25"],
                  "nombre": ["Navidad", "Año Nuevo", "Cariño", "Navidad"],
                  "tipo": ["feriado", "feriado", "comercial", "feriado"],
                  "ambito": ["nacional", "nacional", "nacional", "nacional"]}).to_csv(
        directorio / "feriados.csv", index=False)
    rng = np.random.default_rng(0)
    filas = []
    for d in pd.date_range(fin - timedelta(days=dias - 1), fin):
        for t, base in [(1, 300), (5, 200), (10, 80)]:
            if t == 10 and d < pd.Timestamp("2025-12-15"):
                continue
            for i, (f, _) in enumerate(FAMILIAS):
                promo = int(rng.integers(0, 4))
                nivel = base * (1 + 0.3 * (d.dayofweek >= 5)) * (1 + 0.05 * promo) / (i + 1)
                filas.append((d.date().isoformat(), t, f, int(rng.poisson(nivel)), promo))
    pd.DataFrame(filas, columns=["fecha", "tienda_id", "familia_id", "ventas", "en_promocion"]).to_csv(
        directorio / "historico_ventas.csv", index=False)
    return directorio


@pytest.fixture(scope="session")
def dir_datos(tmp_path_factory) -> Path:
    return escribir_datos(tmp_path_factory.mktemp("datos"))


@pytest.fixture(scope="session")
def catalogos(dir_datos):
    return cat.leer_catalogos(dir_datos)


@pytest.fixture(scope="session")
def historico(dir_datos) -> pd.DataFrame:
    return pd.read_csv(dir_datos / "historico_ventas.csv", parse_dates=["fecha"])


@pytest.fixture
def cfg(tmp_path, dir_datos) -> Configuracion:
    return Configuracion(db_url=f"sqlite:///{tmp_path / 'producto.db'}", mlflow_uri="http://mlflow-falso:5000",
                         dir_datos=dir_datos, dir_cache_modelo=tmp_path / "cache")

