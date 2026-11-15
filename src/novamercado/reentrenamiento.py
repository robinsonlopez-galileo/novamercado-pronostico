"""Pasos del ciclo de mejora continua. Los usan el DAG de Airflow y la inicialización.

Cada paso es una función que recibe y devuelve diccionarios pequeños (aptos para XCom). Los
datos se leen de la base del producto: histórico publicado más observaciones registradas.
"""

from __future__ import annotations

from dataclasses import asdict
from datetime import date, timedelta

import mlflow
from mlflow import MlflowClient

from novamercado import catalogos as cat
from novamercado.configuracion import Configuracion
from novamercado.modelo import compuerta, registro
from novamercado.modelo.entrenamiento import entrenar, evaluar, tabla_entrenamiento
from novamercado.persistencia import repositorio as repo


def _contexto(cfg: Configuracion):
    engine = repo.motor(cfg.db_url)
    catalogos = cat.cargar(str(cfg.dir_datos))
    mlflow.set_tracking_uri(cfg.mlflow_uri)
    return engine, catalogos, MlflowClient(cfg.mlflow_uri)


def planear(cfg: Configuracion) -> dict:
    """Define la ventana de evaluación: los últimos días conocidos, posteriores al fin de
    entrenamiento del modelo vigente para que la comparación sea justa."""
    engine, _, cliente = _contexto(cfg)
    datos = repo.ventas_conocidas(engine)
    ultimo = datos["fecha"].max().date()
    inicio = ultimo - timedelta(days=cfg.dias_evaluacion - 1)
    vigente = registro.version_por_alias(cliente, cfg.nombre_modelo, cfg.alias_vigente)
    plan = {"ultimo_dia": ultimo.isoformat(), "version_vigente": None, "fin_vigente": None}
    if vigente is not None:
        fin_vigente = vigente.tags.get("fin_entrenamiento")
        plan |= {"version_vigente": str(vigente.version), "fin_vigente": fin_vigente}
        if fin_vigente:
            inicio = max(inicio, date.fromisoformat(fin_vigente) + timedelta(days=1))
    plan |= {"ventana_inicio": inicio.isoformat(), "ventana_fin": ultimo.isoformat(),
             "dias_ventana": max((ultimo - inicio).days + 1, 0),
             "fin_entrenamiento": (inicio - timedelta(days=1)).isoformat(),
             "filas": int(len(datos)), "huella_datos": registro.huella_datos(datos)}
    return plan


def entrenar_reto(cfg: Configuracion, plan: dict, origen: str) -> dict:
    """Entrena el reto (boosting) y el baseline con datos hasta fin_entrenamiento, los evalúa en
    la ventana y registra una versión nueva del reto en el Model Registry."""
    engine, catalogos, _ = _contexto(cfg)
    registro.preparar_experimento(cfg.mlflow_uri, cfg.experimento)
    tabla = tabla_entrenamiento(repo.ventas_conocidas(engine), catalogos)
    fin = date.fromisoformat(plan["fin_entrenamiento"])
    v_ini, v_fin = date.fromisoformat(plan["ventana_inicio"]), date.fromisoformat(plan["ventana_fin"])

    base = entrenar("perfil", tabla, fin, catalogos)
    reto = entrenar("boosting", tabla, fin, catalogos)
    m_base = evaluar(base.modelo, tabla, v_ini, v_fin, catalogos) if plan["dias_ventana"] else {}
    m_reto = evaluar(reto.modelo, tabla, v_ini, v_fin, catalogos) if plan["dias_ventana"] else {}

    etiquetas = {"origen": origen, "ventana_evaluacion": f"{v_ini} a {v_fin}",
                 "huella_datos": plan["huella_datos"], "filas_datos": str(plan["filas"]),
                 "fin_entrenamiento": fin.isoformat()}
    metricas = {**{f"{k}_validacion": v for k, v in m_reto.items()},
                **{f"{k}_calibracion": v for k, v in reto.metricas_calibracion.items()},
                **{f"baseline_{k}_validacion": v for k, v in m_base.items()}}
    _, version = registro.registrar_modelo(
        reto.modelo, tabla[tabla["fecha"] <= str(fin)], f"{origen}-boosting", cfg.nombre_modelo,
        parametros={"ventana.inicio": str(v_ini), "ventana.fin": str(v_fin),
                    "fin_entrenamiento": str(fin), "dias_evaluacion": cfg.dias_evaluacion},
        metricas=metricas, etiquetas=etiquetas)
    version_baseline = None
    if plan.get("version_vigente") is None:
        # Sin modelo vigente el baseline también se registra: es el respaldo si el boosting no
        # lo supera, para que el servicio nunca arranque sin modelo.
        _, version_baseline = registro.registrar_modelo(
            base.modelo, tabla[tabla["fecha"] <= str(fin)], f"{origen}-baseline-perfil",
            cfg.nombre_modelo, parametros={"fin_entrenamiento": str(fin)},
            metricas={f"{k}_validacion": v for k, v in m_base.items()}, etiquetas=etiquetas)
        MlflowClient(cfg.mlflow_uri).set_model_version_tag(
            cfg.nombre_modelo, version_baseline, "decision", "respaldo (baseline)")
    else:
        with mlflow.start_run(run_name=f"{origen}-baseline-perfil"):
            mlflow.log_params({"modelo.tipo": "perfil", "fin_entrenamiento": str(fin)})
            mlflow.log_metrics({f"{k}_validacion": v for k, v in m_base.items()})
            mlflow.set_tags(etiquetas)
    return {"version": version, "costo": m_reto.get("costo"), "costo_baseline": m_base.get("costo"),
            "wape": m_reto.get("wape"), "wape_baseline": m_base.get("wape"),
            "version_baseline": version_baseline}


def evaluar_vigente(cfg: Configuracion, plan: dict) -> dict:
    """Costo del modelo vigente en la misma ventana. Vacío si no hay vigente."""
    if not plan.get("version_vigente") or not plan["dias_ventana"]:
        return {"version": plan.get("version_vigente"), "costo": None}
    engine, catalogos, _ = _contexto(cfg)
    modelo = registro.cargar_modelo(f"models:/{cfg.nombre_modelo}/{plan['version_vigente']}")
    tabla = tabla_entrenamiento(repo.ventas_conocidas(engine), catalogos)
    m = evaluar(modelo, tabla, date.fromisoformat(plan["ventana_inicio"]),
                date.fromisoformat(plan["ventana_fin"]), catalogos)
    return {"version": plan["version_vigente"], "costo": m["costo"], "wape": m["wape"]}


def decidir(cfg: Configuracion, plan: dict, reto: dict, vigente: dict) -> dict:
    d = compuerta.decidir(reto.get("costo"), vigente.get("costo"), reto.get("costo_baseline"),
                          plan["dias_ventana"], cfg.mejora_minima)
    return asdict(d)


def aplicar(cfg: Configuracion, plan: dict, reto: dict, decision: dict) -> dict:
    """Mueve @champion si corresponde y devuelve el resultado final de la ejecución."""
    _, _, cliente = _contexto(cfg)
    if decision["promover"]:
        registro.promover(cliente, cfg.nombre_modelo, reto["version"], cfg.alias_vigente,
                          cfg.alias_anterior, decision["motivo"])
        version = reto["version"]
    elif not plan.get("version_vigente") and reto.get("version_baseline"):
        motivo = f"{decision['motivo']}; se usa el baseline porque no había modelo vigente"
        registro.descartar(cliente, cfg.nombre_modelo, reto["version"], decision["motivo"])
        registro.promover(cliente, cfg.nombre_modelo, reto["version_baseline"], cfg.alias_vigente,
                          cfg.alias_anterior, motivo)
        return {"promovido": True, "version": reto["version_baseline"], "motivo": motivo,
                "version_reto": reto["version"]}
    else:
        registro.descartar(cliente, cfg.nombre_modelo, reto["version"], decision["motivo"])
        version = plan.get("version_vigente")
    return {"promovido": bool(decision["promover"]), "version": version, "motivo": decision["motivo"],
            "version_reto": reto["version"]}


def ejecutar_completo(cfg: Configuracion, origen: str) -> dict:
    """Todo el ciclo en un solo proceso (inicialización y pruebas de integración)."""
    plan = planear(cfg)
    reto = entrenar_reto(cfg, plan, origen)
    vigente = evaluar_vigente(cfg, plan)
    return aplicar(cfg, plan, reto, decidir(cfg, plan, reto, vigente)) | {"plan": plan}
