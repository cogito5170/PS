"""Quantity parsing and unit normalisation (deterministic).

Original representations are always kept (``Quantity.raw`` / ``Quantity.unit``);
normalised values are added alongside, never substituted.
"""
from __future__ import annotations

import re
from typing import Optional

from .models import Quantity

WORD_NUMBERS = {
    "zero": 0, "one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7,
    "eight": 8, "nine": 9, "ten": 10, "eleven": 11, "twelve": 12, "fifteen": 15,
    "twenty": 20, "thirty": 30, "forty": 40, "fifty": 50, "hundred": 100,
    "half": 0.5, "a third": 1 / 3, "a quarter": 0.25,
}
SCALES = {"thousand": 1e3, "million": 1e6, "billion": 1e9, "trillion": 1e12,
          "k": 1e3, "m": 1e6, "bn": 1e9,
          "천": 1e3, "만": 1e4, "억": 1e8, "조": 1e12}

# unit token -> (canonical unit, factor to canonical, dimension)
UNITS: dict[str, tuple[str, float, str]] = {
    "%": ("percent", 1, "ratio"), "percent": ("percent", 1, "ratio"),
    "per cent": ("percent", 1, "ratio"), "pct": ("percent", 1, "ratio"),
    "percentage points": ("pp", 1, "ratio_pp"), "percentage point": ("pp", 1, "ratio_pp"),
    "km": ("m", 1000, "length"), "kilometres": ("m", 1000, "length"),
    "kilometers": ("m", 1000, "length"), "m": ("m", 1, "length"), "meters": ("m", 1, "length"),
    "metres": ("m", 1, "length"), "cm": ("m", 0.01, "length"), "mm": ("m", 0.001, "length"),
    "mi": ("m", 1609.344, "length"), "miles": ("m", 1609.344, "length"),
    "feet": ("m", 0.3048, "length"), "ft": ("m", 0.3048, "length"),
    "kg": ("kg", 1, "mass"), "kilograms": ("kg", 1, "mass"), "g": ("kg", 0.001, "mass"),
    "grams": ("kg", 0.001, "mass"), "mg": ("kg", 1e-6, "mass"),
    "milligrams": ("kg", 1e-6, "mass"), "tonnes": ("kg", 1000, "mass"),
    "tons": ("kg", 907.185, "mass"), "lb": ("kg", 0.45359237, "mass"),
    "lbs": ("kg", 0.45359237, "mass"),
    "l": ("l", 1, "volume"), "liters": ("l", 1, "volume"), "litres": ("l", 1, "volume"),
    "ml": ("l", 0.001, "volume"),
    "seconds": ("s", 1, "time"), "minutes": ("s", 60, "time"), "hours": ("s", 3600, "time"),
    "days": ("s", 86400, "time"), "weeks": ("s", 604800, "time"),
    "months": ("s", 2629800, "time"), "years": ("s", 31557600, "time"),
    "km/h": ("m/s", 1 / 3.6, "speed"), "mph": ("m/s", 0.44704, "speed"),
    "m/s": ("m/s", 1, "speed"),
    "kwh": ("J", 3.6e6, "energy"), "mwh": ("J", 3.6e9, "energy"), "j": ("J", 1, "energy"),
    "w": ("W", 1, "power"), "kw": ("W", 1e3, "power"), "mw": ("W", 1e6, "power"),
    "gw": ("W", 1e9, "power"), "watts": ("W", 1, "power"), "kilowatts": ("W", 1e3, "power"),
    "megawatts": ("W", 1e6, "power"), "gigawatts": ("W", 1e9, "power"),
    "kilowatt-hours": ("J", 3.6e6, "energy"), "megawatt-hours": ("J", 3.6e9, "energy"),
    "mmhg": ("mmHg", 1, "pressure"), "pa": ("Pa", 1, "pressure"), "kpa": ("Pa", 1e3, "pressure"),
    "people": ("count", 1, "count"), "persons": ("count", 1, "count"),
    "patients": ("count", 1, "count"), "students": ("count", 1, "count"),
    "cases": ("count", 1, "count"), "jobs": ("count", 1, "count"),
    "points": ("points", 1, "points"), "point": ("points", 1, "points"),
    # Korean
    "퍼센트포인트": ("pp", 1, "ratio_pp"), "%p": ("pp", 1, "ratio_pp"), "퍼센트": ("percent", 1, "ratio"),
    "프로": ("percent", 1, "ratio"), "명": ("count", 1, "count"), "킬로미터": ("m", 1000, "length"),
    "미터": ("m", 1, "length"), "센티미터": ("m", 0.01, "length"), "킬로그램": ("kg", 1, "mass"),
    "그램": ("kg", 0.001, "mass"), "톤": ("kg", 1000, "mass"), "리터": ("l", 1, "volume"),
    "개월": ("s", 2629800, "time"), "시간": ("s", 3600, "time"), "메가와트": ("W", 1e6, "power"),
    "기가와트": ("W", 1e9, "power"), "킬로와트": ("W", 1e3, "power"), "점": ("points", 1, "points"),
    "곳": ("count", 1, "count"), "개교": ("count", 1, "count"), "개": ("count", 1, "count"),
    "그루": ("count", 1, "count"), "회": ("count", 1, "count"), "건": ("count", 1, "count"),
    "마리": ("count", 1, "count"), "장": ("count", 1, "count"), "가구": ("count", 1, "count"),
    "위": ("rank", 1, "rank"), "㎍/㎥": ("ug/m3", 1, "concentration"), "μg/m³": ("ug/m3", 1, "concentration"),
    "ug/m3": ("ug/m3", 1, "concentration"), "ppm": ("ppm", 1, "concentration"), "mg/l": ("mg/l", 1, "concentration"),
    "db": ("dB", 1, "sound"), "데시벨": ("dB", 1, "sound"),
    "seats": ("count", 1, "count"), "votes": ("count", 1, "count"),
    "species": ("count", 1, "count"), "hectares": ("m2", 10000, "area"),
    "ha": ("m2", 10000, "area"), "km2": ("m2", 1e6, "area"),
    "square kilometres": ("m2", 1e6, "area"), "square kilometers": ("m2", 1e6, "area"),
}
TEMPERATURE = {
    "°c": "C", "degrees celsius": "C", "celsius": "C", "degrees c": "C", "°f": "F",
    "degrees fahrenheit": "F", "fahrenheit": "F", "degrees f": "F", "kelvin": "K",
    "k": "K", "도": "C", "℃": "C",
}
CURRENCY_PREFIX = {"$": "USD", "us$": "USD", "€": "EUR", "£": "GBP", "¥": "JPY", "₩": "KRW"}
CURRENCY_SUFFIX = {"usd": "USD", "dollars": "USD", "eur": "EUR", "euros": "EUR",
                   "gbp": "GBP", "pounds sterling": "GBP", "yen": "JPY",
                   "원": "KRW", "달러": "USD", "유로": "EUR", "엔": "JPY"}

_NUM = r"(?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d+)?"
_unit_alts = sorted(set(UNITS) | set(TEMPERATURE) | set(CURRENCY_SUFFIX), key=len, reverse=True)
_UNIT_RE = "|".join(re.escape(u) for u in _unit_alts)
_SCALE_RE = r"(?:(?:thousand|million|billion|trillion|bn)\b|천|만|억|조)"
_WORDNUM_RE = "|".join(sorted((re.escape(w) for w in WORD_NUMBERS), key=len, reverse=True))

QUANTITY_RE = re.compile(
    rf"(?P<approx>(?:about|around|approximately|roughly|nearly|almost|some|over|under|more than|less than|at least|up to|~)\s+)?"
    rf"(?P<cur>US\$|\$|€|£|¥|₩)?\s?"
    rf"(?P<num>{_NUM}|\b(?:{_WORDNUM_RE})\b)"
    rf"(?:\s?(?P<scale>{_SCALE_RE}))?"
    rf"(?:\s?(?P<unit>{_UNIT_RE})(?![A-Za-z]))?",
    re.I,
)
YEAR_RE = re.compile(r"\b(1[0-9]{3}|20[0-9]{2}|2100)s?\b")


def parse_number(s: str) -> Optional[float]:
    s = s.strip().lower()
    if s in WORD_NUMBERS:
        return float(WORD_NUMBERS[s])
    try:
        return float(s.replace(",", ""))
    except ValueError:
        return None


def normalize(q: Quantity) -> Quantity:
    unit = (q.unit or "").lower()
    if unit in TEMPERATURE:
        scale = TEMPERATURE[unit]
        v = q.value
        if q.kind in ("change",):
            c = v if scale in ("C", "K") else v * 5 / 9
        else:
            c = v if scale == "C" else (v - 32) * 5 / 9 if scale == "F" else v - 273.15
        q.norm_value, q.norm_unit, q.dimension = c, "degC", "temperature"
    elif unit.startswith("currency:"):
        code = (q.unit or "").split(":", 1)[1].upper()
        q.norm_value, q.norm_unit, q.dimension = q.value, code, f"currency:{code}"
    elif unit in UNITS:
        cu, f, dim = UNITS[unit]
        q.norm_value, q.norm_unit, q.dimension = q.value * f, cu, dim
    elif unit in CURRENCY_SUFFIX:
        cur = CURRENCY_SUFFIX[unit]
        q.norm_value, q.norm_unit, q.dimension = q.value, cur, f"currency:{cur}"
    elif not unit:
        q.norm_value, q.norm_unit, q.dimension = q.value, None, "dimensionless"
    return q


def find_quantities(text: str) -> list[tuple[int, int, Quantity]]:
    """All quantities in ``text`` with spans. Bare 4-digit years are returned with
    kind='year' so callers can treat them as time rather than magnitudes."""
    out: list[tuple[int, int, Quantity]] = []
    for m in QUANTITY_RE.finditer(text):
        num = parse_number(m.group("num"))
        if num is None:
            continue
        unit = m.group("unit")
        cur = m.group("cur")
        scale = m.group("scale")
        raw = m.group(0).strip()
        start, end = m.start(), m.end()
        if m.group("approx") is None and raw and raw[0].isspace():
            start += 1
        is_word = not re.match(r"\d", m.group("num"))
        if is_word and not unit and not scale and not cur:
            # word numbers without a unit are too ambiguous ("one of the")
            continue
        value = num * (SCALES[scale.lower()] if scale else 1)
        kind = "level"
        if (not unit and not cur and not scale and YEAR_RE.fullmatch(m.group("num"))
                and "," not in m.group("num")):
            kind = "year"
        q = Quantity(value=value, unit=unit, raw=raw,
                     approximate=bool(m.group("approx")) and m.group("approx").strip().lower()
                     in ("about", "around", "approximately", "roughly", "nearly", "almost", "some", "~"),
                     kind=kind)
        if cur:
            q.unit = f"currency:{CURRENCY_PREFIX[cur.lower()]}"
        out.append((start, end, normalize(q)))
    return out


def comparable(a: Quantity, b: Quantity) -> bool:
    if a.kind == "year" or b.kind == "year":
        return a.kind == b.kind
    da, db = a.dimension, b.dimension
    if da == db:
        return True
    return False


def values_conflict(a: Quantity, b: Quantity, rel_tol: float = 0.01) -> bool:
    """True when two comparable quantities differ beyond tolerance. Approximate
    quantities ("about 20%") get a 10 % relative tolerance."""
    if a.norm_value is None or b.norm_value is None:
        return False
    if a.approximate or b.approximate:
        rel_tol = max(rel_tol, 0.10)
    va, vb = a.norm_value, b.norm_value
    denom = max(abs(va), abs(vb), 1e-12)
    return abs(va - vb) / denom > rel_tol


def fmt(q: Optional[Quantity]) -> str:
    if q is None:
        return ""
    return q.raw
