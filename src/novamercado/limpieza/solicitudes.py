"""Limpieza de las solicitudes completas de predicción y de observación.

Reglas generales (no por caso del catálogo):

1. Nombres de campo: se comparan sin acentos, mayúsculas ni separadores contra una lista de
   sinónimos. Coincidencia exacta con un sinónimo -> reparar; parecido alto -> advertir;
   campo desconocido -> se ignora y se advierte; campo obligatorio ausente -> rechazar.
2. Valores: un formato distinto con una sola lectura posible -> reparar; varias lecturas o un
   supuesto -> advertir; ninguna lectura defendible del dato principal -> rechazar.
3. Familias: nombre reconocible -> reparar; repetida con el mismo valor -> reparar; repetida
   con valores distintos -> advertir (predicción) o no registrar (observación); faltantes ->
   advertir. Una familia desconocida no se inventa: se omite y se advierte.
"""

from __future__ import annotations

import difflib
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import date, timedelta

from pydantic import ValidationError

from novamercado.catalogos import Catalogos
from novamercado.contrato import ObservacionCalidad, SolicitudObservacion, SolicitudPrediccion
from novamercado.limpieza import valores
from novamercado.limpieza.base import Rechazo, Registro, clave, mostrar

# --------------------------------------------------------------------------- sinónimos de campos
_TIENDA = {"tiendaid", "tienda", "idtienda", "store", "storeid", "storenbr", "sucursal",
           "sucursalid", "codigotienda", "tiendacodigo", "numtienda", "numerotienda"}
_FECHA = {"fecha", "date", "dia", "day", "fechapronostico", "fechaprediccion", "fechaventa",
          "fechaventas", "fechaobservacion"}
_FAMILIA = {"familiaid", "familia", "family", "familyid", "idfamilia", "categoria", "category",
            "familiaproducto", "codigofamilia"}
_PROMO = {"enpromocion", "promocion", "promociones", "promo", "promos", "onpromotion",
          "productosenpromocion", "enpromo", "cantidadpromocion", "promocionados"}
_VENTAS = {"ventas", "venta", "unidades", "unidadesvendidas", "sales", "cantidad", "vendido",
           "vendidas", "total"}

CAMPOS_PREDICCION = {
    "tienda_id": _TIENDA, "fecha": _FECHA,
    "familias": {"familias", "familia", "families", "items", "lineas", "detalle", "productos",
                 "categorias", "pedido"},
}
CAMPOS_OBSERVACION = {
    "tienda_id": _TIENDA, "fecha": _FECHA,
    "ventas": {"ventas", "venta", "observaciones", "registros", "items", "lineas", "detalle",
               "familias", "sales"},
}
CAMPOS_ITEM_PREDICCION = {"familia_id": _FAMILIA, "en_promocion": _PROMO}
CAMPOS_ITEM_OBSERVACION = {"familia_id": _FAMILIA, "ventas": _VENTAS}

UMBRAL_PARECIDO = 0.85
Referencia = date | Callable[[int], date | None] | None
DIAS_MAXIMOS_SIN_CALENDARIO = 366
LIMITE_PROMOCION = 100  # el histórico llega a 19 productos en promoción por familia


@dataclass
class PrediccionLimpia:
    solicitud: SolicitudPrediccion
    observaciones: list[ObservacionCalidad]


@dataclass
class ObservacionLimpia:
    solicitud: SolicitudObservacion
    observaciones: list[ObservacionCalidad]
    no_registradas: list[str] = field(default_factory=list)


# --------------------------------------------------------------------------- campos
def _resolver_campos(datos: dict, esquema: dict[str, set[str]], prefijo: str,
                     registro: Registro, obligatorios: tuple[str, ...]) -> dict:
    """Asigna cada clave recibida a un campo del contrato. Devuelve {campo: valor}."""
    encontrados: dict[str, tuple[str, object]] = {}
    for nombre_recibido, valor in datos.items():
        k = clave(nombre_recibido)
        destino = next((c for c, sin in esquema.items() if k == clave(c) or k in sin), None)
        aproximado = False
        if destino is None and k:
            todos = {s: c for c, sin in esquema.items() for s in sin | {clave(c)}}
            parecidos = difflib.get_close_matches(k, list(todos), n=1, cutoff=UMBRAL_PARECIDO)
            if parecidos:
                destino, aproximado = todos[parecidos[0]], True
        ruta = f"{prefijo}{nombre_recibido}"
        if destino is None:
            registro.advertir(ruta, f"campo desconocido {mostrar(nombre_recibido)}; se ignoró")
            continue
        if destino in encontrados:
            previo_nombre, previo_valor = encontrados[destino]
            if previo_valor != valor:
                raise Rechazo(
                    f"los campos {mostrar(previo_nombre)} y {mostrar(nombre_recibido)} indican "
                    f"{destino} con valores distintos", campo=f"{prefijo}{destino}")
            registro.reparar(ruta, f"campo duplicado de {destino} con el mismo valor; se ignoró")
            continue
        encontrados[destino] = (nombre_recibido, valor)
        if nombre_recibido != destino:
            if aproximado:
                registro.advertir(ruta, f"el campo {mostrar(nombre_recibido)} se interpretó como "
                                        f"{mostrar(destino)} por similitud del nombre")
            else:
                registro.reparar(ruta, f"el campo {mostrar(nombre_recibido)} se interpretó como "
                                       f"{mostrar(destino)}")
    for campo in obligatorios:
        if campo not in encontrados:
            raise Rechazo("campo obligatorio ausente", campo=f"{prefijo}{campo}")
    return {c: v for c, (_, v) in encontrados.items()}


# --------------------------------------------------------------------------- familias
def _formas_familia(catalogos: Catalogos) -> dict[str, str]:
    formas: dict[str, str] = {}
    for fila in catalogos.familias.itertuples():
        for texto in (fila.familia_id, fila.nombre):
            formas[clave(texto)] = fila.familia_id
            sin_conectores = clave(" ".join(p for p in str(texto).lower().split() if p not in {"y", "de", "e"}))
            formas[sin_conectores] = fila.familia_id
    return formas


def interpretar_familia(valor: object, catalogos: Catalogos, campo: str,
                        registro: Registro) -> str | None:
    """familia_id del catálogo, o None si no se puede reconocer (se advierte)."""
    if valor is None or isinstance(valor, (bool, int, float, dict, list)):
        registro.advertir(campo, f"{mostrar(valor)} no es una familia; se omitió")
        return None
    texto = str(valor)
    if texto in catalogos.familia_ids:
        return texto
    formas = _formas_familia(catalogos)
    k = clave(texto)
    if k in formas:
        registro.reparar(campo, f"{mostrar(texto)} se interpretó como {mostrar(formas[k])}")
        return formas[k]
    parecidos = difflib.get_close_matches(k, list(formas), n=1, cutoff=UMBRAL_PARECIDO) if k else []
    if parecidos:
        destino = formas[parecidos[0]]
        registro.advertir(campo, f"{mostrar(texto)} se interpretó como {mostrar(destino)} por similitud")
        return destino
    registro.advertir(campo, f"familia desconocida {mostrar(texto)}; se omitió")
    return None


def _como_lista(valor: object, nombre_valor: str, campo: str, registro: Registro) -> list:
    """Acepta una lista de objetos o un objeto {familia: valor}."""
    if isinstance(valor, list):
        return valor
    if isinstance(valor, dict):
        registro.reparar(campo, f"se recibió un objeto {{familia: {nombre_valor}}}; se convirtió en lista")
        return [{"familia_id": k, nombre_valor: v} for k, v in valor.items()]
    raise Rechazo(f"se esperaba una lista y se recibió {type(valor).__name__}", campo=campo)


# --------------------------------------------------------------------------- comunes
def _tienda(valor: object, catalogos: Catalogos, registro: Registro) -> int:
    try:
        r = valores.tienda_id(valor)
    except ValueError as e:
        raise Rechazo(str(e), campo="tienda_id") from None
    if r.valor not in catalogos.tienda_ids:
        raise Rechazo(f"la tienda {r.valor} no existe en el catálogo", campo="tienda_id")
    if r.accion:
        getattr(registro, r.accion)("tienda_id", r.detalle)
    return int(r.valor)


def _fecha(valor: object, tienda: int, referencia, catalogos: Catalogos,
           registro: Registro) -> date:
    if callable(referencia):
        referencia = referencia(tienda)
    try:
        r = valores.fecha(valor, referencia)
    except ValueError as e:
        raise Rechazo(str(e), campo="fecha") from None
    if r.accion:
        getattr(registro, r.accion)("fecha", r.detalle)
    d: date = r.valor
    apertura = catalogos.apertura(tienda)
    if d < apertura:
        raise Rechazo(f"{d.isoformat()} es anterior a la apertura de la tienda {tienda} "
                      f"({apertura.isoformat()})", campo="fecha")
    fin = catalogos.fin_calendario
    if d > fin + timedelta(days=DIAS_MAXIMOS_SIN_CALENDARIO):
        raise Rechazo(f"{d.isoformat()} está más de un año después del calendario disponible "
                      f"({fin.isoformat()})", campo="fecha")
    return d


def _validar(modelo, datos: dict):
    try:
        return modelo.model_validate(datos)
    except ValidationError as e:  # salvaguarda: la limpieza debió dejarlo en forma
        primero = e.errors()[0]
        ruta = ".".join(str(p) for p in primero["loc"])
        raise Rechazo(primero["msg"], campo=ruta) from None


# --------------------------------------------------------------------------- predicción
def preparar_prediccion(cuerpo: object, catalogos: Catalogos,
                        referencia: Referencia = None) -> PrediccionLimpia:
    """Limpia una solicitud de POST /v1/prediccion.

    `referencia` es la fecha esperada por el calendario de operación (o una función tienda ->
    fecha); solo sirve para desempatar fechas ambiguas como 05/11/2025."""
    if not isinstance(cuerpo, dict):
        raise Rechazo("el cuerpo debe ser un objeto JSON")
    registro = Registro()
    campos = _resolver_campos(cuerpo, CAMPOS_PREDICCION, "", registro,
                              obligatorios=("tienda_id", "fecha", "familias"))
    tienda = _tienda(campos["tienda_id"], catalogos, registro)
    fecha = _fecha(campos["fecha"], tienda, referencia, catalogos, registro)
    if fecha > catalogos.fin_calendario:
        registro.advertir("fecha", f"{fecha.isoformat()} está fuera del calendario de feriados "
                                   f"publicado; se supuso que no es feriado")

    items = _como_lista(campos["familias"], "en_promocion", "familias", registro)
    vistos: dict[str, list[tuple[int, int]]] = {}
    for i, item in enumerate(items):
        ruta = f"familias[{i}]"
        if isinstance(item, str):
            item = {"familia_id": item}
            registro.reparar(ruta, "se recibió solo el nombre de la familia")
        if not isinstance(item, dict):
            registro.advertir(ruta, f"elemento {mostrar(item)} no reconocido; se ignoró")
            continue
        try:
            datos = _resolver_campos(item, CAMPOS_ITEM_PREDICCION, f"{ruta}.", registro,
                                     obligatorios=("familia_id",))
        except Rechazo as e:
            registro.advertir(ruta, f"{e.detalle}; se ignoró el elemento")
            continue
        familia = interpretar_familia(datos["familia_id"], catalogos, f"{ruta}.familia_id", registro)
        if familia is None:
            continue
        promo = _promocion(datos.get("en_promocion", None), "en_promocion" in datos,
                           f"{ruta}.en_promocion", registro)
        vistos.setdefault(familia, []).append((i, promo))

    familias: list[dict] = []
    for familia, apariciones in vistos.items():
        promos = [p for _, p in apariciones]
        promo = promos[0]
        if len(apariciones) > 1:
            indices = ", ".join(str(i) for i, _ in apariciones)
            if len(set(promos)) == 1:
                registro.reparar(f"familias[{apariciones[1][0]}]",
                                 f"{familia} repetida con el mismo valor (posiciones {indices}); se usó una vez")
            else:
                promo = max(promos)
                registro.advertir(f"familias[{apariciones[1][0]}]",
                                  f"{familia} repetida con en_promocion distinto {promos} "
                                  f"(posiciones {indices}); se usó el mayor, {promo}")
        familias.append({"familia_id": familia, "en_promocion": promo})

    if not familias:
        raise Rechazo("ninguna familia de la solicitud se pudo reconocer", campo="familias")
    faltan = [f for f in catalogos.familia_ids if f not in vistos]
    if faltan:
        registro.advertir("familias", f"faltan familias que la tienda vende ({', '.join(faltan)}); "
                                      "se pronosticaron suponiendo en_promocion = 0")
        familias += [{"familia_id": f, "en_promocion": 0} for f in faltan]

    solicitud = _validar(SolicitudPrediccion, {"tienda_id": tienda, "fecha": fecha, "familias": familias})
    return PrediccionLimpia(solicitud, registro.observaciones)


def _promocion(valor: object, presente: bool, campo: str, registro: Registro) -> int:
    if not presente or valor is None:
        registro.advertir(campo, "sin cantidad en promoción; se supuso 0")
        return 0
    try:
        r = valores.entero_no_negativo(valor, maximo=LIMITE_PROMOCION)
    except ValueError as e:
        registro.advertir(campo, f"{e}; se supuso 0")
        return 0
    if r.accion:
        getattr(registro, r.accion)(campo, r.detalle)
    return int(r.valor)


# --------------------------------------------------------------------------- observación
def preparar_observacion(cuerpo: object, catalogos: Catalogos,
                         referencia: Referencia = None) -> ObservacionLimpia:
    """Limpia una solicitud de POST /v1/observaciones. Nunca inventa una venta: lo que no se
    puede interpretar sin supuestos no se registra y se advierte."""
    if not isinstance(cuerpo, dict):
        raise Rechazo("el cuerpo debe ser un objeto JSON")
    registro = Registro()
    campos = _resolver_campos(cuerpo, CAMPOS_OBSERVACION, "", registro,
                              obligatorios=("tienda_id", "fecha", "ventas"))
    tienda = _tienda(campos["tienda_id"], catalogos, registro)
    fecha = _fecha(campos["fecha"], tienda, referencia, catalogos, registro)

    items = _como_lista(campos["ventas"], "ventas", "ventas", registro)
    vistos: dict[str, list[tuple[int, int]]] = {}
    no_registradas: list[str] = []
    for i, item in enumerate(items):
        ruta = f"ventas[{i}]"
        if not isinstance(item, dict):
            registro.advertir(ruta, f"elemento {mostrar(item)} no reconocido; no se registró")
            continue
        try:
            datos = _resolver_campos(item, CAMPOS_ITEM_OBSERVACION, f"{ruta}.", registro,
                                     obligatorios=("familia_id",))
        except Rechazo as e:
            registro.advertir(ruta, f"{e.detalle}; no se registró")
            continue
        familia = interpretar_familia(datos["familia_id"], catalogos, f"{ruta}.familia_id", registro)
        if familia is None:
            continue
        valor = datos.get("ventas")
        if valor is None:
            registro.advertir(f"{ruta}.ventas", f"{familia} sin ventas; no se registró")
            no_registradas.append(familia)
            continue
        try:
            r = valores.entero_no_negativo(valor)
        except ValueError as e:
            motivo = (f"ventas negativas ({mostrar(valor)}), probablemente devoluciones; no se "
                      "registró para no inventar la venta real") if "negativo" in str(e) else \
                     f"{e}; no se registró"
            registro.advertir(f"{ruta}.ventas", motivo)
            no_registradas.append(familia)
            continue
        if r.accion:
            getattr(registro, r.accion)(f"{ruta}.ventas", r.detalle)
        vistos.setdefault(familia, []).append((i, int(r.valor)))

    ventas: list[dict] = []
    for familia, apariciones in vistos.items():
        cantidades = [v for _, v in apariciones]
        if len(apariciones) > 1:
            indices = ", ".join(str(i) for i, _ in apariciones)
            if len(set(cantidades)) > 1:
                registro.advertir(f"ventas[{apariciones[1][0]}]",
                                  f"{familia} repetida con ventas distintas {cantidades} "
                                  f"(posiciones {indices}); no se registró")
                no_registradas.append(familia)
                continue
            registro.reparar(f"ventas[{apariciones[1][0]}]",
                             f"{familia} repetida con el mismo valor (posiciones {indices}); se registró una vez")
        ventas.append({"familia_id": familia, "ventas": cantidades[0]})

    if not ventas and not no_registradas:
        raise Rechazo("ninguna venta de la solicitud se pudo reconocer", campo="ventas")
    faltan = [f for f in catalogos.familia_ids if f not in vistos and f not in no_registradas]
    if faltan:
        registro.advertir("ventas", f"la solicitud no incluye ventas de {', '.join(faltan)}; para esas "
                                    "familias se conserva lo registrado antes o el día queda sin dato")

    solicitud = _validar(SolicitudObservacion, {"tienda_id": tienda, "fecha": fecha, "ventas": ventas})
    return ObservacionLimpia(solicitud, registro.observaciones, sorted(set(no_registradas)))
