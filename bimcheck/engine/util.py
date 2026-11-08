"""Small helpers shared by the engine: units, number formatting, geometry, text."""
from __future__ import annotations

import math
import re
from typing import Any, Iterable, Sequence

# --------------------------------------------------------------------------- units
# factor that converts a value expressed in the *rule's* unit to the model base unit (m, m2, deg ...)
_UNIT_FACTOR = {
    "": 1.0, "m": 1.0, "metre": 1.0, "meter": 1.0, "cm": 0.01, "mm": 0.001,
    "m2": 1.0, "m²": 1.0, "m^2": 1.0, "cm2": 1e-4, "cm²": 1e-4, "mm2": 1e-6,
    "deg": 1.0, "°": 1.0, "%": 1.0, "ratio": 1.0, "count": 1.0, "adet": 1.0, "kat": 1.0,
}
_UNIT_BASE = {
    "": "", "m": "m", "metre": "m", "meter": "m", "cm": "m", "mm": "m",
    "m2": "m²", "m²": "m²", "m^2": "m²", "cm2": "m²", "cm²": "m²", "mm2": "m²",
    "deg": "°", "°": "°", "%": "%", "ratio": "", "count": "", "adet": "", "kat": "",
}


def unit_factor(unit: str | None) -> float:
    return _UNIT_FACTOR.get((unit or "").strip().lower(), 1.0)


def base_unit(unit: str | None) -> str:
    u = (unit or "").strip().lower()
    return _UNIT_BASE.get(u, unit or "")


def to_base(value: Any, unit: str | None) -> float | None:
    """Convert a rule value (in `unit`) to model base units. None stays None."""
    if value is None:
        return None
    try:
        return float(value) * unit_factor(unit)
    except (TypeError, ValueError):
        return None


def fnum(v: float | None, nd: int = 2) -> str:
    if v is None:
        return "?"
    s = f"{v:.{nd}f}"
    return s


def fmt(v: float | None, unit: str = "m", nd: int | None = None) -> str:
    if v is None:
        return "n/a"
    if nd is None:
        nd = 3 if unit == "" else 2
    s = f"{v:.{nd}f}"
    return f"{s} {unit}".strip()


def num(x: Any) -> float | None:
    """Return float(x) when x is a real finite number (bool excluded), else None."""
    if isinstance(x, bool) or x is None:
        return None
    try:
        f = float(x)
    except (TypeError, ValueError):
        return None
    return f if math.isfinite(f) else None


# --------------------------------------------------------------------------- text
_TR_MAP = str.maketrans("İıŞşĞğÜüÖöÇç", "IiSsGgUuOoCc")


def fold(s: Any) -> str:
    """Lower-case, Turkish-diacritic-folded string for keyword matching."""
    if s is None:
        return ""
    return str(s).translate(_TR_MAP).lower()


def has_kw(text: Any, words: Iterable[str]) -> bool:
    t = fold(text)
    return any(fold(w) in t for w in words)


_NUM_RE = re.compile(r"(\d+(?:[.,]\d+)?)\s*(cm|mm|m2|m²|m³|m|metre|%)?", re.I)


def numbers_in_text(text: str) -> list[float]:
    """Numbers (in metres / m² as written) found in free text; cm/mm converted to m."""
    out: list[float] = []
    for m in _NUM_RE.finditer(text or ""):
        raw, unit = m.group(1), (m.group(2) or "").lower()
        if "." not in raw and "," not in raw and not unit:
            continue  # bare integers are usually article numbers / counts
        try:
            v = float(raw.replace(",", "."))
        except ValueError:
            continue
        if unit == "cm":
            v /= 100.0
        elif unit == "mm":
            v /= 1000.0
        out.append(v)
    return out


# --------------------------------------------------------------------------- geometry
def poly_area(poly: Sequence[Sequence[float]] | None) -> float | None:
    if not poly or len(poly) < 3:
        return None
    s = 0.0
    n = len(poly)
    for i in range(n):
        x1, y1 = poly[i][0], poly[i][1]
        x2, y2 = poly[(i + 1) % n][0], poly[(i + 1) % n][1]
        s += x1 * y2 - x2 * y1
    return abs(s) / 2.0


def poly_centroid(poly: Sequence[Sequence[float]]) -> tuple[float, float]:
    a = 0.0
    cx = cy = 0.0
    n = len(poly)
    for i in range(n):
        x1, y1 = poly[i][0], poly[i][1]
        x2, y2 = poly[(i + 1) % n][0], poly[(i + 1) % n][1]
        c = x1 * y2 - x2 * y1
        a += c
        cx += (x1 + x2) * c
        cy += (y1 + y2) * c
    if abs(a) < 1e-12:
        xs = [p[0] for p in poly]
        ys = [p[1] for p in poly]
        return sum(xs) / len(xs), sum(ys) / len(ys)
    return cx / (3 * a), cy / (3 * a)


def _shapely_poly(poly):
    from shapely.geometry import Polygon
    p = Polygon([(float(x), float(y)) for x, y in poly])
    if not p.is_valid:
        p = p.buffer(0)
    return p


def min_rect(poly: Sequence[Sequence[float]] | None):
    """Min-area rotated rectangle of a polygon.

    Returns dict(short, long, short_seg=(p,q), long_seg=(p,q), centre) in 2D, or None.
    `short_seg` connects midpoints of the two long edges (its length == `short`)."""
    if not poly or len(poly) < 3:
        return None
    try:
        p = _shapely_poly(poly)
        if p.is_empty:
            return None
        rect = p.minimum_rotated_rectangle
        c = list(rect.exterior.coords)[:4]
        if len(c) < 4:
            return None
    except Exception:
        return None
    (x0, y0), (x1, y1), (x2, y2), (x3, y3) = c
    l0 = math.hypot(x1 - x0, y1 - y0)
    l1 = math.hypot(x2 - x1, y2 - y1)

    def mid(a, b):
        return ((a[0] + b[0]) / 2, (a[1] + b[1]) / 2)

    if l0 <= l1:
        short_seg = (mid(c[1], c[2]), mid(c[3], c[0]))
        long_seg = (mid(c[0], c[1]), mid(c[2], c[3]))
        short, long_ = l0, l1
    else:
        short_seg = (mid(c[0], c[1]), mid(c[2], c[3]))
        long_seg = (mid(c[1], c[2]), mid(c[3], c[0]))
        short, long_ = l1, l0
    centre = ((x0 + x2) / 2, (y0 + y2) / 2)
    return {"short": short, "long": long_, "short_seg": short_seg, "long_seg": long_seg, "centre": centre}


def seg3(p, q, z: float | None) -> tuple[list[float], list[float]]:
    zz = 0.0 if z is None else float(z)
    return [float(p[0]), float(p[1]), zz], [float(q[0]), float(q[1]), zz]


def dim(p1, p2, label: str, kind: str = "linear") -> dict:
    return {"p1": [round(float(c), 4) for c in p1], "p2": [round(float(c), 4) for c in p2],
            "label": label, "kind": kind}


def bbox_center(bb: dict | None) -> list[float] | None:
    if not bb:
        return None
    try:
        mn, mx = bb["min"], bb["max"]
        return [(mn[i] + mx[i]) / 2.0 for i in range(3)]
    except Exception:
        return None


def bbox_dims(bb: dict | None) -> tuple[float, float, float] | None:
    if not bb:
        return None
    try:
        mn, mx = bb["min"], bb["max"]
        return (mx[0] - mn[0], mx[1] - mn[1], mx[2] - mn[2])
    except Exception:
        return None
