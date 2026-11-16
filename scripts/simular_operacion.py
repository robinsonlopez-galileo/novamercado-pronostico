"""Simula la operación diaria de las tiendas contra la API y mide el costo de las sugerencias.

Sirve para el modo de ensayo: se levanta el producto con HISTORICO_HASTA=2025-12-31 (en .env),
de modo que enero y febrero de 2026 quedan fuera del histórico cargado, y este script los
reproduce día a día como lo haría el programa de evaluación:

  1. antes de las solicitudes del día D llegan las observaciones reales de D-1;
  2. cada tienda pide el pronóstico de D (con la promoción real del día);
  3. una fracción de solicitudes llega con problemas (formatos, nombres, campos);
  4. cada N días se pide un reentrenamiento y se espera su resultado.

    python scripts/simular_operacion.py --desde 2026-01-01 --hasta 2026-02-28 \
        --datos datos --api http://localhost:8000 --reentrenar-cada 14 --salida evidencia/simulacion

No modifica nada fuera de la API. Requiere: requests y pandas.
"""

from __future__ import annotations

import argparse
import json
import random
import time
from datetime import date, timedelta
from pathlib import Path

import pandas as pd
import requests


def defecto(cuerpo: dict, rng: random.Random, tipo: str) -> tuple[dict, str]:
    """Introduce un problema al azar (incluye algunos que no están en el catálogo)."""
    c = json.loads(json.dumps(cuerpo))
    clave = "familias" if tipo == "prediccion" else "ventas"
    valor = "en_promocion" if tipo == "prediccion" else "ventas"
    opcion = rng.choice(["tienda_texto", "fecha_dmy", "fecha_iso_hora", "familia_mayusculas",
                         "numero_texto", "campo_renombrado", "familia_repetida", "campo_extra",
                         "familia_espacios"] + (["faltan_familias"] if tipo == "prediccion" else ["negativo"]))
    if opcion == "tienda_texto":
        c["tienda_id"] = f"T{c['tienda_id']:02d}"
    elif opcion == "fecha_dmy":
        c["fecha"] = date.fromisoformat(c["fecha"]).strftime("%d/%m/%Y")
    elif opcion == "fecha_iso_hora":
        c["fecha"] = c["fecha"] + "T00:00:00"
    elif opcion == "familia_mayusculas":
        c[clave][0]["familia_id"] = c[clave][0]["familia_id"].upper()
    elif opcion == "familia_espacios":
        c[clave][1]["familia_id"] = " " + c[clave][1]["familia_id"].replace("_", " ").title() + " "
    elif opcion == "numero_texto":
        c[clave][2][valor] = f"{c[clave][2][valor]:,}" if valor == "ventas" else str(c[clave][2][valor])
    elif opcion == "campo_renombrado":
        c["tienda"] = c.pop("tienda_id")
    elif opcion == "familia_repetida":
        c[clave].append(dict(c[clave][0]))
    elif opcion == "campo_extra":
        c["sistema_origen"] = "pos-v2"
    elif opcion == "faltan_familias":
        c[clave] = c[clave][:-2]
    elif opcion == "negativo":
        c[clave][3][valor] = -abs(c[clave][3][valor]) - 1
    return c, opcion


def esperar_reentrenamiento(api: str, run_id: str, limite_s: int = 600) -> dict:
    inicio = time.time()
    while time.time() - inicio < limite_s:
        r = requests.get(f"{api}/admin/reentrenar/{run_id}", timeout=10).json()
        if r.get("estado") != "en_curso":
            r["duracion_s"] = round(time.time() - inicio)
            return r
        time.sleep(5)
    return {"estado": "sin_terminar"}


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--desde", type=date.fromisoformat, required=True)
    p.add_argument("--hasta", type=date.fromisoformat, required=True)
    p.add_argument("--datos", type=Path, default=Path("datos"))
    p.add_argument("--api", default="http://localhost:8000")
    p.add_argument("--reentrenar-cada", type=int, default=14)
    p.add_argument("--prob-defecto", type=float, default=0.25)
    p.add_argument("--salida", type=Path, default=Path("evidencia/simulacion"))
    p.add_argument("--semilla", type=int, default=7)
    a = p.parse_args()
    rng = random.Random(a.semilla)
    a.salida.mkdir(parents=True, exist_ok=True)

    real = pd.read_csv(a.datos / "historico_ventas.csv", parse_dates=["fecha"])
    costos = pd.read_csv(a.datos / "costos.csv").set_index("familia_id")
    real = real[(real["fecha"] >= pd.Timestamp(a.desde - timedelta(days=1))) & (real["fecha"] <= pd.Timestamp(a.hasta))]
    filas, ejemplos, reentrenos, estados = [], {}, [], {}
    d = a.desde
    while d <= a.hasta:
        ayer = real[real["fecha"] == pd.Timestamp(d - timedelta(days=1))]
        for tienda, g in ayer.groupby("tienda_id"):
            cuerpo = {"tienda_id": int(tienda), "fecha": (d - timedelta(days=1)).isoformat(),
                      "ventas": [{"familia_id": f, "ventas": int(v)} for f, v in zip(g["familia_id"], g["ventas"])]}
            tipo_defecto = None
            if rng.random() < a.prob_defecto:
                cuerpo, tipo_defecto = defecto(cuerpo, rng, "observacion")
            r = requests.post(f"{a.api}/v1/observaciones", json=cuerpo, timeout=30)
            estados[("observacion", r.status_code, r.json().get("calidad", {}).get("estado"))] = \
                estados.get(("observacion", r.status_code, r.json().get("calidad", {}).get("estado")), 0) + 1
            if tipo_defecto and f"obs_{tipo_defecto}" not in ejemplos:
                ejemplos[f"obs_{tipo_defecto}"] = {"solicitud": cuerpo, "status": r.status_code, "respuesta": r.json()}
        hoy = real[real["fecha"] == pd.Timestamp(d)]
        for tienda, g in hoy.groupby("tienda_id"):
            cuerpo = {"tienda_id": int(tienda), "fecha": d.isoformat(),
                      "familias": [{"familia_id": f, "en_promocion": int(x)} for f, x in zip(g["familia_id"], g["en_promocion"])]}
            tipo_defecto = None
            if rng.random() < a.prob_defecto:
                cuerpo, tipo_defecto = defecto(cuerpo, rng, "prediccion")
            r = requests.post(f"{a.api}/v1/prediccion", json=cuerpo, timeout=30)
            j = r.json()
            estados[("prediccion", r.status_code, j.get("calidad", {}).get("estado"))] = \
                estados.get(("prediccion", r.status_code, j.get("calidad", {}).get("estado")), 0) + 1
            if tipo_defecto and f"pred_{tipo_defecto}" not in ejemplos:
                ejemplos[f"pred_{tipo_defecto}"] = {"solicitud": cuerpo, "status": r.status_code, "respuesta": j}
            if r.status_code == 200:
                verdad = dict(zip(g["familia_id"], g["ventas"]))
                for pr in j["predicciones"]:
                    filas.append({"fecha": d.isoformat(), "tienda_id": int(tienda), "familia_id": pr["familia_id"],
                                  "venta_esperada": pr["venta_esperada"], "cantidad_sugerida": pr["cantidad_sugerida"],
                                  "ventas": verdad.get(pr["familia_id"]), "version_modelo": j["version_modelo"]})
        dia = (d - a.desde).days + 1
        if a.reentrenar_cada and dia % a.reentrenar_cada == 0:
            r = requests.post(f"{a.api}/admin/reentrenar", timeout=30)
            resultado = {"fecha_simulada": d.isoformat(), "status": r.status_code, **r.json()}
            if r.status_code == 202:
                resultado |= esperar_reentrenamiento(a.api, r.json()["id"])
            reentrenos.append(resultado)
            print("reentrenamiento", resultado, flush=True)
        print(d, "listo", flush=True)
        d += timedelta(days=1)

    df = pd.DataFrame(filas).dropna(subset=["ventas"])
    cf = df["familia_id"].map(costos["costo_faltante"])
    cs = df["familia_id"].map(costos["costo_sobrante"])
    df["costo"] = cf * (df["ventas"] - df["cantidad_sugerida"]).clip(lower=0) + \
        cs * (df["cantidad_sugerida"] - df["ventas"]).clip(lower=0)
    df.to_csv(a.salida / "predicciones_vs_real.csv", index=False)
    resumen = {
        "periodo": f"{a.desde} a {a.hasta}",
        "predicciones": len(df),
        "costo_total": round(float(df["costo"].sum()), 1),
        "costo_por_registro": round(float(df["costo"].mean()), 3),
        "wape": round(float((df["venta_esperada"] - df["ventas"]).abs().sum() / df["ventas"].sum()), 4),
        "costo_por_version": df.groupby("version_modelo")["costo"].mean().round(3).to_dict(),
        "respuestas": {f"{k[0]} {k[1]} {k[2]}": v for k, v in sorted(estados.items(), key=str)},
        "reentrenamientos": reentrenos,
    }
    (a.salida / "resumen.json").write_text(json.dumps(resumen, indent=2, ensure_ascii=False), encoding="utf-8")
    (a.salida / "ejemplos_respuestas.json").write_text(json.dumps(ejemplos, indent=2, ensure_ascii=False), encoding="utf-8")
    print(json.dumps({k: v for k, v in resumen.items() if k != "reentrenamientos"}, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
