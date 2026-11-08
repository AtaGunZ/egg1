"""Geometry helpers on normalised entities: flattening, block expansion, bounding boxes, shapely conversion."""
from __future__ import annotations

import math
from typing import Iterable, Iterator

import numpy as np

from .reader import bulge_points

Pt = tuple[float, float]


def arc_points(c: Pt, r: float, a0: float, a1: float, max_seg_angle: float = math.radians(12)) -> list[Pt]:
    if a1 <= a0:
        a1 += 2 * math.pi
    n = max(int((a1 - a0) / max_seg_angle), 2)
    return [(c[0] + r * math.cos(a0 + (a1 - a0) * i / n), c[1] + r * math.sin(a0 + (a1 - a0) * i / n)) for i in range(n + 1)]


def ellipse_points(c: Pt, major: Pt, ratio: float, a0: float, a1: float, max_seg_angle: float = math.radians(15)) -> list[Pt]:
    if a1 <= a0:
        a1 += 2 * math.pi
    n = max(int((a1 - a0) / max_seg_angle), 4)
    mx, my = major
    out = []
    for i in range(n + 1):
        t = a0 + (a1 - a0) * i / n
        out.append((c[0] + mx * math.cos(t) - ratio * my * math.sin(t), c[1] + my * math.cos(t) + ratio * mx * math.sin(t)))
    return out


def entity_lines(e: dict) -> list[tuple[list[Pt], bool]]:
    """Return [(points, closed)] for linework entities; [] for non-linework."""
    t = e["t"]
    if t == "LINE":
        return [([e["p1"], e["p2"]], False)]
    if t == "POLY":
        pts = e["pts"]
        if len(pts) < 2:
            return []
        if any(abs(p[2]) > 1e-9 for p in pts):
            pl = bulge_points(pts, e["closed"])
            if e["closed"] and pl and pl[0] != pl[-1]:
                pass
            return [(pl, e["closed"])]
        return [([(p[0], p[1]) for p in pts], e["closed"])]
    if t == "ARC":
        return [(arc_points(e["c"], e["r"], e["a0"], e["a1"]), False)]
    if t == "CIRCLE":
        pts = arc_points(e["c"], e["r"], 0.0, 2 * math.pi, math.radians(20))
        return [(pts, True)]
    if t == "ELLIPSE":
        full = abs((e["a1"] - e["a0"]) - 2 * math.pi) < 1e-6 or e["a1"] == e["a0"]
        return [(ellipse_points(e["c"], e["major"], e["ratio"], e["a0"], e["a1"] if not full else e["a0"] + 2 * math.pi), full)]
    if t == "SOLID":
        pts = e["pts"]
        if len(pts) == 4:
            pts = [pts[0], pts[1], pts[3], pts[2]]
        return [(pts, True)]
    if t == "HATCH":
        return [(p, True) for p in e["paths"] if len(p) >= 3]
    if t == "SPLINE" or t == "LEADER":
        return [(e["pts"], False)] if len(e["pts"]) >= 2 else []
    return []


def transform_pt(p: Pt, ins: dict, base: Pt, ox: float = 0.0, oy: float = 0.0) -> Pt:
    x, y = p[0] - base[0], p[1] - base[1]
    x *= ins["sx"]
    y *= ins["sy"]
    c, s = math.cos(ins["rot"]), math.sin(ins["rot"])
    return (ins["pos"][0] + ox + x * c - y * s, ins["pos"][1] + oy + x * s + y * c)


def _xf_entity(e: dict, ins: dict, base: Pt, ox: float, oy: float, layer: str) -> dict | None:
    t = e["t"]
    f = lambda p: transform_pt(p, ins, base, ox, oy)  # noqa: E731
    mirrored = (ins["sx"] * ins["sy"]) < 0
    if t in ("LINE",):
        return {"t": "LINE", "layer": layer, "p1": f(e["p1"]), "p2": f(e["p2"]), "blk": True}
    if t == "POLY":
        pts = [(*f((p[0], p[1])), -p[2] if mirrored else p[2]) for p in e["pts"]]
        return {"t": "POLY", "layer": layer, "pts": pts, "closed": e["closed"], "blk": True}
    if t in ("ARC", "CIRCLE", "ELLIPSE", "SOLID", "SPLINE", "LEADER"):
        out = []
        for pts, closed in entity_lines(e):
            out.append(([f(p) for p in pts], closed))
        if not out:
            return None
        pts, closed = out[0]
        return {"t": "POLY", "layer": layer, "pts": [(p[0], p[1], 0.0) for p in pts], "closed": closed, "blk": True, "src": t}
    if t == "HATCH":
        return {"t": "HATCH", "layer": layer, "paths": [[f(p) for p in path] for path in e["paths"]], "solid": e["solid"], "pattern": e["pattern"], "blk": True}
    if t == "TEXT":
        r = dict(e)
        r["layer"] = layer
        r["pos"] = f(e["pos"])
        r["rot"] = e["rot"] + ins["rot"]
        r["h"] = e["h"] * abs(ins["sy"])
        r["blk"] = True
        return r
    return None


def expand_insert(ins: dict, blocks: dict[str, list[dict]], base_pts: dict[str, Pt], depth: int = 0, max_depth: int = 4) -> Iterator[dict]:
    """Yield transformed block entities (world coordinates) for one INSERT (array aware). Layer '0' inherits insert layer."""
    name = ins["name"]
    ents = blocks.get(name)
    if not ents or depth > max_depth:
        return
    base = base_pts.get(name, (0.0, 0.0))
    for ci in range(max(ins.get("cols", 1), 1)):
        for ri in range(max(ins.get("rows", 1), 1)):
            ox, oy = ci * ins.get("dx", 0.0), ri * ins.get("dy", 0.0)
            for e in ents:
                layer = ins["layer"] if e["layer"] == "0" else e["layer"]
                if e["t"] == "INSERT":
                    sub = dict(e)
                    sub["pos"] = transform_pt(e["pos"], ins, base, ox, oy)
                    sub["sx"] = e["sx"] * ins["sx"]
                    sub["sy"] = e["sy"] * ins["sy"]
                    sub["rot"] = e["rot"] + ins["rot"]
                    sub["layer"] = layer
                    yield from expand_insert(sub, blocks, base_pts, depth + 1, max_depth)
                else:
                    x = _xf_entity(e, ins, base, ox, oy, layer)
                    if x is not None:
                        yield x


def bbox_of_points(pts: Iterable[Pt]) -> tuple[float, float, float, float] | None:
    arr = np.asarray(list(pts), dtype=float)
    if arr.size == 0:
        return None
    return (float(arr[:, 0].min()), float(arr[:, 1].min()), float(arr[:, 0].max()), float(arr[:, 1].max()))


def entity_bbox(e: dict) -> tuple[float, float, float, float] | None:
    t = e["t"]
    if t == "LINE":
        (x1, y1), (x2, y2) = e["p1"], e["p2"]
        return (min(x1, x2), min(y1, y2), max(x1, x2), max(y1, y2))
    if t == "CIRCLE" or t == "ARC":
        c, r = e["c"], e["r"]
        return (c[0] - r, c[1] - r, c[0] + r, c[1] + r)
    if t == "ELLIPSE":
        c, m = e["c"], e["major"]
        a = math.hypot(*m)
        return (c[0] - a, c[1] - a, c[0] + a, c[1] + a)
    if t == "TEXT":
        x, y = e["pos"]
        w = max(len(e["text"]), 1) * e["h"] * 0.6
        return (x, y, x + w * math.cos(e["rot"]), y + w * math.sin(e["rot"]) + e["h"])
    if t == "INSERT":
        x, y = e["pos"]
        return (x, y, x, y)
    pts = []
    for p, _ in entity_lines(e):
        pts.extend(p)
    if t == "DIM":
        pts = [e["p1"], e["p2"], e["defpt"]]
    if t == "POINT":
        pts = [e["pos"]]
    return bbox_of_points(pts) if pts else None


def poly_area(pts: list[Pt]) -> float:
    """Signed shoelace area (CCW positive)."""
    a = 0.0
    n = len(pts)
    for i in range(n):
        x0, y0 = pts[i]
        x1, y1 = pts[(i + 1) % n]
        a += x0 * y1 - x1 * y0
    return a / 2


def min_rotated_rect_dims(poly) -> tuple[float, float]:
    """(short side, long side) of the minimum-area rotated rectangle of a shapely polygon."""
    rect = poly.minimum_rotated_rectangle
    xs, ys = rect.exterior.coords.xy
    d1 = math.hypot(xs[1] - xs[0], ys[1] - ys[0])
    d2 = math.hypot(xs[2] - xs[1], ys[2] - ys[1])
    return (min(d1, d2), max(d1, d2))
