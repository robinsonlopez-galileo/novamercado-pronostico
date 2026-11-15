"""Interpretación de valores sueltos: números, identificadores de tienda y fechas.

Son funciones puras. Devuelven el valor interpretado y, si hubo que transformarlo, la acción
(reparar o advertir) con su explicación. Si no hay una interpretación defendible lanzan
ValueError con el motivo, y quien las llama decide la política.
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass
from datetime import date, timedelta

from novamercado.limpieza.base import mostrar, sin_acentos


@dataclass(frozen=True)
class Interpretacion:
    valor: object
    accion: str | None = None  # None, "reparar" o "advertir"
    detalle: str | None = None


# --------------------------------------------------------------------------- números
_SOLO_DIGITOS = re.compile(r"^[+-]?\d+$")
_MILES_COMA = re.compile(r"^[+-]?\d{1,3}(,\d{3})+$")
_MILES_PUNTO = re.compile(r"^[+-]?\d{1,3}(\.\d{3})+$")
_DECIMAL_PUNTO = re.compile(r"^[+-]?\d+\.\d+$")
_DECIMAL_COMA = re.compile(r"^[+-]?\d+,\d+$")
_MILES_COMA_DEC_PUNTO = re.compile(r"^[+-]?\d{1,3}(,\d{3})+\.\d+$")
_MILES_PUNTO_DEC_COMA = re.compile(r"^[+-]?\d{1,3}(\.\d{3})+,\d+$")


def lecturas(valor: object) -> list[float]:
    """Lecturas posibles de un número escrito de varias formas, en orden de preferencia.

    "1,234" y "1.234" admiten dos lecturas (separador de miles o decimal); se prefiere la de
    miles porque las cantidades son unidades enteras. ValueError si no es un número."""
    if isinstance(valor, bool) or valor is None:
        raise ValueError(f"{mostrar(valor)} no es un número")
    if isinstance(valor, (int, float)):
        if isinstance(valor, float) and not math.isfinite(valor):
            raise ValueError(f"{mostrar(valor)} no es un número finito")
        return [float(valor)]
    if not isinstance(valor, str):
        raise ValueError(f"{mostrar(valor)} no es un número")
    texto = valor.strip().replace("\u00a0", "").replace(" ", "").replace("_", "")
    if _SOLO_DIGITOS.match(texto):
        return [float(int(texto))]
    if _MILES_COMA.match(texto):  # "1,234": miles; también podría ser 1.234
        return [float(texto.replace(",", "")), float(texto.replace(",", "."))] if texto.count(",") == 1 \
            else [float(texto.replace(",", ""))]
    if _MILES_PUNTO.match(texto):  # "1.234": miles; también podría ser 1.234
        return [float(texto.replace(".", "")), float(texto)] if texto.count(".") == 1 \
            else [float(texto.replace(".", ""))]
    if _MILES_COMA_DEC_PUNTO.match(texto):  # "1,234.5"
        return [float(texto.replace(",", ""))]
    if _MILES_PUNTO_DEC_COMA.match(texto):  # "1.234,5"
        return [float(texto.replace(".", "").replace(",", "."))]
    if _DECIMAL_PUNTO.match(texto):
        return [float(texto)]
    if _DECIMAL_COMA.match(texto):  # "812,0"
        return [float(texto.replace(",", "."))]
    raise ValueError(f"{mostrar(valor)} no es un número")


def numero(valor: object) -> float:
    """Lectura preferida de un número. ValueError si no es un número."""
    return lecturas(valor)[0]


def entero_no_negativo(valor: object, maximo: int | None = None) -> Interpretacion:
    """Cantidad entera (unidades o productos).

    - Un formato distinto con una sola lectura entera -> reparar ("1,292" -> 1292).
    - Varias lecturas enteras ("1.000": mil o uno) -> se elige la plausible y se advierte.
    - Un valor no entero -> se redondea y se advierte.
    - Un valor mayor que `maximo` -> se acota y se advierte.
    ValueError si no es número o si es negativo (la política la decide quien llama)."""
    candidatos = lecturas(valor)
    if candidatos[0] < 0:
        raise ValueError(f"{mostrar(valor)} es negativo")
    enteros = [c for c in candidatos if c == int(c)]
    if isinstance(valor, int) and not isinstance(valor, bool):
        resultado = Interpretacion(int(valor))
    elif len(enteros) > 1:
        plausibles = [c for c in enteros if maximo is None or c <= maximo] or enteros
        elegido = int(plausibles[0])
        otras = ", ".join(str(int(c)) for c in enteros if int(c) != elegido)
        resultado = Interpretacion(elegido, "advertir", f"{mostrar(valor)} es ambiguo (también podría ser "
                                                         f"{otras}); se usó {elegido}")
    elif enteros:
        elegido = int(enteros[0])
        resultado = Interpretacion(elegido, "reparar", f"{mostrar(valor)} se interpretó como {elegido}")
    else:
        elegido = int(round(candidatos[0]))
        resultado = Interpretacion(elegido, "advertir", f"{mostrar(valor)} no es entero; se redondeó a {elegido}")
    if maximo is not None and resultado.valor > maximo:
        return Interpretacion(maximo, "advertir", f"{mostrar(valor)} está fuera del rango plausible; "
                                                  f"se acotó a {maximo}")
    return resultado


# --------------------------------------------------------------------------- tienda
def tienda_id(valor: object) -> Interpretacion:
    """Identificador de tienda. Repara texto con prefijos o ceros a la izquierda ("T05" -> 5)."""
    if isinstance(valor, bool) or valor is None:
        raise ValueError(f"{mostrar(valor)} no identifica una tienda")
    if isinstance(valor, int):
        return Interpretacion(valor)
    if isinstance(valor, float):
        if valor.is_integer():
            return Interpretacion(int(valor), "reparar", f"{mostrar(valor)} se interpretó como {int(valor)}")
        raise ValueError(f"{mostrar(valor)} no es un identificador entero")
    if isinstance(valor, str):
        grupos = re.findall(r"\d+", valor)
        if len(grupos) == 1 and re.fullmatch(r"\s*(?:[A-Za-z]+[\s_#\-.:]*|#\s*)?\d+\s*", valor):
            n = int(grupos[0])
            return Interpretacion(n, "reparar", f"{mostrar(valor)} se interpretó como {n}")
    raise ValueError(f"{mostrar(valor)} no identifica una tienda de forma inequívoca")


# --------------------------------------------------------------------------- fechas
_MESES = {
    "ene": 1, "enero": 1, "jan": 1, "january": 1,
    "feb": 2, "febrero": 2, "february": 2,
    "mar": 3, "marzo": 3, "march": 3,
    "abr": 4, "abril": 4, "apr": 4, "april": 4,
    "may": 5, "mayo": 5,
    "jun": 6, "junio": 6, "june": 6,
    "jul": 7, "julio": 7, "july": 7,
    "ago": 8, "agosto": 8, "aug": 8, "august": 8,
    "sep": 9, "sept": 9, "septiembre": 9, "setiembre": 9, "september": 9,
    "oct": 10, "octubre": 10, "october": 10,
    "nov": 11, "noviembre": 11, "november": 11,
    "dic": 12, "diciembre": 12, "dec": 12, "december": 12,
}
_ISO = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_ISO_HORA = re.compile(r"^(\d{4}-\d{2}-\d{2})[T ]\d{1,2}:\d{2}(:\d{2}(\.\d+)?)?(Z|[+-]\d{2}:?\d{2})?$")
_ANIO_PRIMERO = re.compile(r"^(\d{4})[/.\-](\d{1,2})[/.\-](\d{1,2})$")
_COMPACTA = re.compile(r"^(\d{4})(\d{2})(\d{2})$")
_DIA_MES_ANIO = re.compile(r"^(\d{1,2})[/.\-](\d{1,2})[/.\-](\d{2}|\d{4})$")


def _construir(anio: int, mes: int, dia: int) -> date | None:
    try:
        return date(anio, mes, dia)
    except ValueError:
        return None


def _con_nombre_de_mes(texto: str) -> date | None:
    limpio = sin_acentos(texto.lower()).replace(",", " ").replace(".", " ")
    limpio = re.sub(r"\bde(l)?\b", " ", limpio)
    partes = [p for p in re.split(r"[\s/\-]+", limpio) if p]
    meses = [p for p in partes if p in _MESES]
    numeros = [p for p in partes if p.isdigit()]
    if len(meses) != 1 or len(numeros) != 2 or len(partes) != 3:
        return None
    anio = next((int(n) for n in numeros if len(n) == 4), None)
    dia = next((int(n) for n in numeros if len(n) <= 2), None)
    if anio is None or dia is None:
        return None
    return _construir(anio, _MESES[meses[0]], dia)


def fecha(valor: object, referencia: date | None = None) -> Interpretacion:
    """Fecha de la solicitud. `referencia` es la fecha que el calendario de operación espera
    (el día siguiente a la última observación de la tienda); solo se usa para desempatar
    lecturas día/mes ambiguas, nunca el reloj del sistema."""
    if isinstance(valor, bool) or valor is None:
        raise ValueError(f"{mostrar(valor)} no es una fecha")
    if isinstance(valor, int) and _COMPACTA.match(str(valor)):
        valor = str(valor)
    if not isinstance(valor, str):
        raise ValueError(f"{mostrar(valor)} no es una fecha en un formato reconocible")
    texto = valor.strip()
    if _ISO.match(texto):
        d = _construir(*map(int, texto.split("-")))
        if d is None:
            raise ValueError(f"{mostrar(valor)} no es una fecha válida")
        if texto != valor:
            return Interpretacion(d, "reparar", f"{mostrar(valor)} se interpretó como {d.isoformat()}")
        return Interpretacion(d)
    m = _ISO_HORA.match(texto)
    if m:
        d = _construir(*map(int, m.group(1).split("-")))
        if d is None:
            raise ValueError(f"{mostrar(valor)} no es una fecha válida")
        return Interpretacion(d, "reparar", f"{mostrar(valor)} se interpretó como {d.isoformat()} (se ignoró la hora)")
    for patron in (_ANIO_PRIMERO, _COMPACTA):
        m = patron.match(texto)
        if m:
            d = _construir(int(m.group(1)), int(m.group(2)), int(m.group(3)))
            if d is None:
                raise ValueError(f"{mostrar(valor)} no es una fecha válida")
            return Interpretacion(d, "reparar", f"{mostrar(valor)} se interpretó como {d.isoformat()}")
    m = _DIA_MES_ANIO.match(texto)
    if m:
        a, b, anio_txt = int(m.group(1)), int(m.group(2)), m.group(3)
        anio = int(anio_txt) if len(anio_txt) == 4 else 2000 + int(anio_txt)
        dia_mes = _construir(anio, b, a)  # convención local: día/mes/año
        mes_dia = _construir(anio, a, b)
        candidatas = {d for d in (dia_mes, mes_dia) if d is not None}
        if not candidatas:
            raise ValueError(f"{mostrar(valor)} no es una fecha válida")
        corto = len(anio_txt) == 2
        if len(candidatas) == 1:
            d = candidatas.pop()
            if corto:
                return Interpretacion(d, "advertir", f"{mostrar(valor)} se interpretó como {d.isoformat()} (año de dos dígitos)")
            return Interpretacion(d, "reparar", f"{mostrar(valor)} se interpretó como {d.isoformat()}")
        # Ambigua (por ejemplo 05/11/2025): se desempata con el calendario de operación.
        if referencia is not None:
            cercanas = [d for d in candidatas if abs((d - referencia).days) <= 7]
            if len(cercanas) == 1:
                d = cercanas[0]
                return Interpretacion(
                    d, "reparar",
                    f"{mostrar(valor)} se interpretó como {d.isoformat()}: es la única lectura "
                    f"compatible con el calendario de operación de la tienda",
                )
        return Interpretacion(
            dia_mes, "advertir",
            f"{mostrar(valor)} es ambigua; se supuso día/mes/año ({dia_mes.isoformat()}), "
            "la convención local",
        )
    d = _con_nombre_de_mes(texto)
    if d is not None:
        return Interpretacion(d, "reparar", f"{mostrar(valor)} se interpretó como {d.isoformat()}")
    raise ValueError(f"{mostrar(valor)} no es una fecha en un formato reconocible")


def un_dia_despues(d: date | None) -> date | None:
    return d + timedelta(days=1) if d else None

