"""Madde 43 - garden wall height."""
from __future__ import annotations

from ..finding import Env, M, R, describe
from ..judge import judge, judge_two
from ..util import dim, fmt, has_kw, num
from ..view import ModelView
from . import register
from .common import need_building_model

GARDEN_KW = ("bahce", "garden", "fence", "boundary", "cit ", "parmaklik", "site wall", "retaining", "istinat", "gartenmauer",
             "einfriedung", "perimeter wall", "compound wall")


def garden_walls(bm: ModelView) -> list[dict]:
    out = []
    for w in bm.of_kind("wall"):
        txt = f"{w.get('name') or ''} {w.get('object_type') or ''} {w.get('long_name') or ''} {(w.get('props') or {}).get('Reference') or ''} "
        if has_kw(txt, GARDEN_KW) and not has_kw(txt, ("istinat", "retaining")):
            out.append(w)
    return out


def _front_info(env: Env, w: dict):
    """True if the wall is in front of the building's front line, False if behind, None if unknown."""
    try:
        from shapely.geometry import LineString, Point
        from ..view import parcel_info
        pi = parcel_info(env.ctx, env.dm)
        idx = env.ctx.get("front_edge_index")
        fp = env.bm.footprint()
        if not pi["polygon"] or idx is None or not fp:
            return None
        poly = pi["polygon"]
        n = len(poly)
        edge = LineString([poly[idx % n], poly[(idx + 1) % n]])
        c = w.get("bbox")
        if not c:
            return None
        pt = Point((c["min"][0] + c["max"][0]) / 2, (c["min"][1] + c["max"][1]) / 2)
        return edge.distance(pt) < edge.distance(fp["geom"])
    except Exception:
        return None


@register("garden_wall_height")
def garden_wall_height(env: Env) -> list[dict]:
    na = need_building_model(env, "walls")
    if na:
        return na
    bm = env.bm
    walls = garden_walls(bm)
    if not walls:
        return [env.na("No garden/boundary walls identified in the model (looked for wall names such as bahçe duvarı, garden wall, fence)",
                       "Modelde bahçe duvarı tespit edilemedi")]
    tol = env.tol(0.005)
    single = env.ctx.get("is_single_dwelling") is True
    out = []
    for w in walls:
        ms = w.get("measures") or {}
        h, p = num(ms.get("height")), (w.get("provenance") or {}).get("height")
        if h is None and w.get("bbox"):
            h, p = w["bbox"]["max"][2] - w["bbox"]["min"][2], "geometry"
        front = _front_info(env, w)
        ex = list(env.exceptions)
        if single:
            ex.append("Villa / single-dwelling areas: walls facing the street up to 2.00 m (Madde 43(4))")
        kw = dict(tol=tol, prov=p, min_prov=env.min_provenance, semi=env.semi, exceptions=ex, legal=env.legal, label="wall height")
        if env.overridden("limit"):
            lim, case = env.limit("limit"), "project override"
            v = judge(h, "<=", lim, **kw)
        elif front is True:
            lim, case = 0.50, "in front of the building line (street side)"
            v = judge(h, "<=", lim, **kw)
        elif front is False:
            lim, case = 1.50, "behind the building line"
            v = judge(h, "<=", lim, **kw)
        else:
            v, which = judge_two(h, "<=", 0.50, 1.50, reason="missing_context",
                                 hint="Walls in front of the building line may be 0.50 m high, behind it 1.50 m. The wall's position "
                                      "relative to the building front could not be determined (needs parcel polygon + front_edge_index).",
                                 **kw)
            lim, case = (0.50 if which == "strict" else 1.50), "position relative to building line unknown"
        nm = ModelView.name(w)
        en, tr = describe(f"Garden wall '{nm}'", f"Bahçe duvarı '{nm}'", "height", "yükseklik", h, "m", "<=", lim)
        en += f" ({case}; a railing up to 1.00 m may be added on top)"
        bb = w.get("bbox")
        dl = []
        if bb and h is not None:
            cx, cy = (bb["min"][0] + bb["max"][0]) / 2, (bb["min"][1] + bb["max"][1]) / 2
            dl = [dim([cx, cy, bb["min"][2]], [cx, cy, bb["min"][2] + h], f"height {fmt(h, 'm')}", "linear")]
        out.append(env.from_verdict(v, w["guid"], en, tr, measured=M(h, "m", p), required=R("<=", lim, "m"),
                                    elements=[w["guid"]], storey_id=w.get("storey_id"), anchor=bm.anchor(w), dimensions=dl))
    return out
