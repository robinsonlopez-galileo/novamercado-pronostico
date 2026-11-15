"""Construcción de variables para el modelo.

Una sola función sirve para entrenar y para predecir: recibe las ventas conocidas y las filas
objetivo, y para cada objetivo solo usa información de días estrictamente anteriores a su fecha.
Así el modelo ve en producción exactamente las mismas variables con que se entrenó y no hay
fuga de información: el día D se predice con las observaciones hasta D-1, más las promociones
del día D, que llegan en la solicitud, y el calendario de feriados, que se conoce de antemano.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from novamercado.catalogos import Catalogos

VENTANA_HISTORIA_DIAS = 120  # historia que necesita la predicción de un día

COLUMNAS_NUMERICAS = [
    "en_promocion", "dia_semana", "dia_mes", "mes", "dia_anio", "fin_de_mes", "quincena",
    "feriado", "feriado_local", "medio_dia", "comercial", "pago",
    "vispera_feriado", "post_feriado", "vispera_comercial",
    "lag_1", "ultimo", "media_7", "media_14", "media_28", "media_91", "mediana_28",
    "media_dia_semana_4", "std_28", "dias_con_dato_28", "tendencia_7_28",
    "promo_media_28", "promo_relativa", "dias_sin_dato",
]
COLUMNAS_CATEGORICAS = ["tienda_cat", "familia_cat", "tipo_cat"]
COLUMNAS = COLUMNAS_CATEGORICAS + COLUMNAS_NUMERICAS


def _calendario(fechas: pd.DatetimeIndex, catalogos: Catalogos) -> pd.DataFrame:
    """Indicadores de calendario por fecha y ciudad (los feriados locales dependen de la ciudad)."""
    fer = catalogos.feriados.copy()
    ciudades = sorted(catalogos.tiendas["ciudad"].unique())
    filas = []
    for ciudad in ciudades:
        aplica = fer[(fer["ambito"] == "nacional") | (fer["ambito"] == ciudad)]
        df = pd.DataFrame(index=fechas)
        for tipo, col in [("feriado", "feriado"), ("medio_dia", "medio_dia"),
                          ("comercial", "comercial"), ("pago", "pago")]:
            dias = set(aplica.loc[aplica["tipo"] == tipo, "fecha"])
            df[col] = df.index.isin(list(dias)).astype(int)
        locales = set(fer.loc[(fer["ambito"] == ciudad) & (fer["tipo"] == "feriado"), "fecha"])
        df["feriado_local"] = df.index.isin(list(locales)).astype(int)
        feriados = set(aplica.loc[aplica["tipo"].isin(["feriado"]), "fecha"])
        comerciales = set(aplica.loc[aplica["tipo"] == "comercial", "fecha"])
        df["vispera_feriado"] = (df.index + pd.Timedelta(days=1)).isin(list(feriados)).astype(int)
        df["post_feriado"] = (df.index - pd.Timedelta(days=1)).isin(list(feriados)).astype(int)
        df["vispera_comercial"] = (df.index + pd.Timedelta(days=1)).isin(list(comerciales)).astype(int)
        df["ciudad"] = ciudad
        filas.append(df.rename_axis("fecha").reset_index())
    return pd.concat(filas, ignore_index=True)


def construir_features(ventas: pd.DataFrame, objetivos: pd.DataFrame,
                       catalogos: Catalogos) -> pd.DataFrame:
    """Variables para cada fila de `objetivos`.

    ventas: tienda_id, fecha, familia_id, ventas y opcionalmente en_promocion (días conocidos).
    objetivos: tienda_id, fecha, familia_id, en_promocion (días a predecir o a entrenar).
    Devuelve `objetivos` con las columnas de COLUMNAS, en el mismo orden de filas.
    """
    obj = objetivos[["tienda_id", "fecha", "familia_id", "en_promocion"]].copy()
    obj["fecha"] = pd.to_datetime(obj["fecha"])
    obj["tienda_id"] = obj["tienda_id"].astype(int)
    v = ventas.copy()
    v["fecha"] = pd.to_datetime(v["fecha"])
    if "en_promocion" not in v:
        v["en_promocion"] = np.nan

    tiendas = catalogos.tienda_ids
    familias = catalogos.familia_ids
    inicio = min(v["fecha"].min() if len(v) else obj["fecha"].min(), obj["fecha"].min())
    fechas = pd.date_range(inicio, obj["fecha"].max(), freq="D")
    columnas = pd.MultiIndex.from_product([tiendas, familias], names=["tienda_id", "familia_id"])

    def ancho(col: str) -> pd.DataFrame:
        s = v.pivot_table(index="fecha", columns=["tienda_id", "familia_id"], values=col, aggfunc="last")
        return s.reindex(index=fechas, columns=columnas)

    y = ancho("ventas").astype(float)
    p = ancho("en_promocion").astype(float)
    previo = y.shift(1)  # solo días anteriores
    f: dict[str, pd.DataFrame] = {
        "lag_1": previo,
        "ultimo": previo.ffill(limit=28),
        "media_7": previo.rolling(7, min_periods=1).mean(),
        "media_14": previo.rolling(14, min_periods=1).mean(),
        "media_28": previo.rolling(28, min_periods=1).mean(),
        "media_91": previo.rolling(91, min_periods=7).mean(),
        "mediana_28": previo.rolling(28, min_periods=1).median(),
        "std_28": previo.rolling(28, min_periods=3).std(),
        "dias_con_dato_28": previo.rolling(28, min_periods=1).count(),
        "promo_media_28": p.shift(1).rolling(28, min_periods=1).mean(),
    }
    mismo_dia = pd.concat([y.shift(k) for k in (7, 14, 21, 28)], keys=range(4))
    f["media_dia_semana_4"] = mismo_dia.groupby(level=1).mean()
    posicion = pd.DataFrame(np.tile(np.arange(len(fechas), dtype=float)[:, None], (1, len(columnas))),
                            index=fechas, columns=columnas)
    ultimo_conocido = posicion.where(y.notna()).shift(1).ffill()
    f["dias_sin_dato"] = posicion - ultimo_conocido  # 1 = se conoce el día anterior

    largo = pd.concat({k: d.unstack() for k, d in f.items()}, axis=1)
    largo = largo.rename_axis(["tienda_id", "familia_id", "fecha"]).reset_index()
    salida = obj.merge(largo, on=["fecha", "tienda_id", "familia_id"], how="left")

    salida["tendencia_7_28"] = salida["media_7"] / (salida["media_28"] + 1.0)
    salida["promo_relativa"] = salida["en_promocion"] - salida["promo_media_28"]
    d = salida["fecha"]
    salida["dia_semana"] = d.dt.dayofweek
    salida["dia_mes"] = d.dt.day
    salida["mes"] = d.dt.month
    salida["dia_anio"] = d.dt.dayofyear
    salida["fin_de_mes"] = (d.dt.days_in_month - d.dt.day <= 1).astype(int)
    salida["quincena"] = d.dt.day.isin([14, 15, 16]).astype(int)

    ciudad = catalogos.tiendas["ciudad"]
    salida["ciudad"] = salida["tienda_id"].map(ciudad)
    cal = _calendario(pd.DatetimeIndex(sorted(salida["fecha"].unique())), catalogos)
    salida = salida.merge(cal, on=["fecha", "ciudad"], how="left")

    salida["tienda_cat"] = salida["tienda_id"].map({t: i for i, t in enumerate(tiendas)})
    salida["familia_cat"] = salida["familia_id"].map({fa: i for i, fa in enumerate(familias)})
    tipos = catalogos.tipos_tienda
    salida["tipo_cat"] = salida["tienda_id"].map(catalogos.tiendas["tipo"]).map(
        {t: i for i, t in enumerate(tipos)})
    for c in COLUMNAS:
        salida[c] = salida[c].astype(float)
    return salida
