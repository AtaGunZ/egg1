"""Measurement overlay geometry (IFC world, Z-up) for the findings' `dimensions`."""
from __future__ import annotations

import math

from .util import bbox_center, bbox_dims, dim, fmt, min_rect, num, seg3
from .view import ModelView


def _horiz_axis(el: dict) -> tuple[float, float]:
    """Unit vector along the longer horizontal bbox extent (wall direction for doors/windows)."""
    d = bbox_dims(el.get("bbox"))
    if not d:
        return 1.0, 0.0
    return (1.0, 0.0) if d[0] >= d[1] else (0.0, 1.0)


def _across_axis(el: dict) -> tuple[float, float]:
    ux, uy = _horiz_axis(el)
    return uy, ux


def horizontal_across(el: dict, length: float, label: str, *, z: float | None = None, along: bool = True,
                      kind: str = "linear") -> list[dict]:
    """Centred horizontal segment of `length` through the element centre (along its long axis by default)."""
    c = bbox_center(el.get("bbox")) or el.get("anchor")
    if not c or length is None:
        return []
    ux, uy = _horiz_axis(el) if along else _across_axis(el)
    zz = z if z is not None else c[2]
    h = length / 2.0
    return [dim([c[0] - ux * h, c[1] - uy * h, zz], [c[0] + ux * h, c[1] + uy * h, zz], label, kind)]


def vertical_at(point, z0: float, length: float, label: str, kind: str = "linear") -> list[dict]:
    if point is None or length is None or z0 is None:
        return []
    return [dim([point[0], point[1], z0], [point[0], point[1], z0 + length], label, kind)]


def door_dims(view: ModelView, el: dict, width: float | None, height: float | None) -> list[dict]:
    out: list[dict] = []
    bb = el.get("bbox")
    if not bb:
        return out
    c = bbox_center(bb)
    d = bbox_dims(bb)
    if width is not None:
        out += horizontal_across(el, width, f"width {fmt(width, 'm')}", z=bb["min"][2] + min(1.0, d[2] / 2))
    if height is not None:
        ux, uy = _horiz_axis(el)
        off = (width or 0) / 2.0 + 0.05
        out += vertical_at([c[0] + ux * off, c[1] + uy * off], bb["min"][2], height, f"height {fmt(height, 'm')}")
    return out


def window_dims(view: ModelView, el: dict, width: float | None, sill: float | None,
                height: float | None = None) -> list[dict]:
    out: list[dict] = []
    bb = el.get("bbox")
    if not bb:
        return out
    c = bbox_center(bb)
    if sill is not None:
        floor = bb["min"][2] - sill
        out += vertical_at([c[0], c[1]], floor, sill, f"sill {fmt(sill, 'm')}", "clearance")
    if width is not None:
        out += horizontal_across(el, width, f"width {fmt(width, 'm')}", z=c[2])
    if height is not None and sill is None:
        out += vertical_at([c[0], c[1]], bb["min"][2], height, f"height {fmt(height, 'm')}")
    return out


def space_dims(view: ModelView, sp: dict, measure: str, value: float | None, label: str | None = None) -> list[dict]:
    z = view.floor_z(sp)
    z = 0.0 if z is None else z
    fp = view.measure(sp, "footprint")
    anchor = view.anchor(sp)
    out: list[dict] = []
    if measure in ("height", "clear_height"):
        if anchor is None or value is None:
            return out
        return vertical_at(anchor, z, value, label or f"height {fmt(value, 'm')}", "clearance")
    mr = min_rect(fp) if fp else None
    if measure == "min_width":
        if mr:
            p, q = mr["short_seg"]
            s = seg3(p, q, z + 0.02)
            out.append(dim(s[0], s[1], label or f"min. width {fmt(mr['short'], 'm')}", "linear"))
        return out
    if measure == "max_length":
        if mr:
            p, q = mr["long_seg"]
            s = seg3(p, q, z + 0.02)
            out.append(dim(s[0], s[1], label or f"length {fmt(mr['long'], 'm')}", "linear"))
        return out
    if measure in ("net_floor_area", "gross_floor_area", "area"):
        if mr:
            for key, nm in (("long_seg", "L"), ("short_seg", "W")):
                p, q = mr[key]
                s = seg3(p, q, z + 0.02)
                ln = mr["long"] if key == "long_seg" else mr["short"]
                out.append(dim(s[0], s[1], f"{fmt(ln, 'm')}", "linear"))
            xs = [pt[0] for pt in fp]
            ys = [pt[1] for pt in fp]
            s = seg3((min(xs), min(ys)), (max(xs), max(ys)), z + 0.05)
            out.append(dim(s[0], s[1], label or (f"area {fmt(value, 'm²')}" if value is not None else "area"), "area"))
        return out
    return out


def stair_dims(view: ModelView, el: dict, measure: str, value: float | None) -> list[dict]:
    bb = el.get("bbox")
    c = bbox_center(bb) if bb else el.get("anchor")
    if not c or value is None:
        return []
    if measure == "riser_height":
        z0 = bb["min"][2] if bb else c[2]
        return vertical_at([c[0], c[1]], z0, value, f"riser {fmt(value * 100, 'cm', 1)}", "linear")
    if measure == "tread_depth":
        ux, uy = _horiz_axis(el)
        z0 = bb["min"][2] if bb else c[2]
        return [dim([c[0], c[1], z0], [c[0] + ux * value, c[1] + uy * value, z0], f"tread {fmt(value * 100, 'cm', 1)}", "linear")]
    if measure == "width":
        return horizontal_across(el, value, f"width {fmt(value, 'm')}", along=False)
    return []


def element_dims(view: ModelView, el: dict, measure: str, value: float | None, unit: str = "m") -> list[dict]:
    """Best-effort overlay for a (kind, measure) pair used by declarative rules."""
    kind = el.get("kind")
    if value is None:
        return []
    try:
        if kind == "space":
            return space_dims(view, el, measure, value)
        if kind == "door":
            if measure == "height":
                return door_dims(view, el, None, value)
            return door_dims(view, el, value, None)
        if kind == "window":
            if measure == "sill_height":
                return window_dims(view, el, None, value)
            if measure == "height":
                return window_dims(view, el, None, None, value)
            return window_dims(view, el, value, None)
        if kind == "stair":
            return stair_dims(view, el, measure, value)
        bb = el.get("bbox")
        c = bbox_center(bb) if bb else el.get("anchor")
        if not c:
            return []
        z0 = bb["min"][2] if bb else c[2]
        if kind in ("railing", "wall", "column", "roof") and measure in ("height", "max_height_z"):
            return vertical_at([c[0], c[1]], z0, value, f"height {fmt(value, 'm')}")
        if kind in ("slab", "wall", "covering") and measure == "thickness":
            if kind == "slab":
                return vertical_at([c[0], c[1]], z0, value, f"thickness {fmt(value, 'm')}")
            return horizontal_across(el, value, f"thickness {fmt(value, 'm')}", along=False)
        if measure in ("length",) and bb:
            return horizontal_across(el, value, f"length {fmt(value, 'm')}", z=c[2])
    except Exception:
        return []
    return []
