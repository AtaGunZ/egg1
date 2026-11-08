"""Madde 32(2)-(3) - light wells (ışıklık) and air shafts (hava bacası)."""
from __future__ import annotations

from .. import dims
from ..finding import Env, M, R
from ..judge import judge, worst
from ..util import fmt, has_kw, min_rect, num, poly_area
from ..view import ModelView
from . import register
from .common import Part, get_spaces, merge_parts, parts_extra

LIGHTWELL_KW = ("isiklik", "aydinlik", "light well", "lightwell", "light-well", "lichthof", "lichtschacht", "lightcourt", "light court")
AIRSHAFT_KW = ("hava bacasi", "air shaft", "airshaft", "vent shaft", "ventilation shaft", "luftschacht", "lueftungsschacht")


def kind_of_space(sp: dict) -> str | None:
    t = f"{sp.get('name') or ''} {sp.get('long_name') or ''}"
    if has_kw(t, AIRSHAFT_KW):
        return "air_shaft"
    if has_kw(t, LIGHTWELL_KW):
        return "light_well"
    return None


@register("light_well_size")
def light_well_size(env: Env) -> list[dict]:
    spaces, source = get_spaces(env)
    if not spaces:
        return [env.na("No spaces available to identify light wells", "Işıklık tespiti için mekân verisi yok")]
    bm = env.bm
    wells = [(s, kind_of_space(s)) for s in spaces]
    part = env.params.get("part")
    wells = [(s, k) for s, k in wells if k and (part is None or part == k or (part == "shaft" and k == "air_shaft"))]
    if not wells:
        return [env.na("No light well / air shaft spaces identified (looked for spaces named ışıklık, light well, hava bacası ...). "
                       "If rooms are lit from a light well, model it as a named space.",
                       "Işıklık / hava bacası mekânı tespit edilemedi", source=source)]
    if bm:
        n = bm.storey_counts()["total"]
    else:
        n = int(num(env.ctx.get("max_storeys")) or (env.dm.floor_plan_count() if env.dm else 0) or 0)
    tall = n >= 7
    lw_side, lw_area = (2.00, 9.00) if tall else (1.50, 4.50)
    if part == "light_well" and env.params.get("min_width"):
        lw_side, lw_area = float(env.params["min_width"]), float(env.params.get("min_area") or lw_area)
        tall = lw_side >= 2.0
    out = []
    tol_w, tol_a = env.tol(0.005), 0.01
    for sp, kind in wells:
        ms = sp["measures"]
        fp = ms.get("footprint")
        pv = sp.get("provenance") or {}
        w, wp = num(ms.get("min_width")), pv.get("min_width")
        if w is None and fp:
            mr = min_rect(fp)
            if mr:
                w, wp = mr["short"], "geometry"
        a, ap = num(ms.get("net_floor_area")), pv.get("net_floor_area")
        if a is None and fp:
            a, ap = poly_area(fp), "geometry"
        if kind == "light_well":
            side, area, label = lw_side, lw_area, ("light well, 7+ storeys" if tall else "light well, 1-6 storeys")
        else:
            side = float(env.params.get("min_width") or 0.60)
            area, label = float(env.params.get("min_area") or 0.36), "air shaft 0.60 x 0.60 m"
        if env.overridden("limit"):
            side = env.limit("limit")
        kw = dict(min_prov=env.min_provenance, semi=env.semi, exceptions=env.exceptions, legal=env.legal)
        parts = [Part("min_width", "short side", "dar kenar", w, wp, ">=", side, "m",
                      judge(w, ">=", side, tol=tol_w, prov=wp, label="short side", **kw)),
                 Part("net_floor_area", "area", "alan", a, ap, ">=", area, "m²",
                      judge(a, ">=", area, tol=tol_a, prov=ap, label="area", **kw))]
        status, reason, hint, prim = merge_parts(parts)
        nm = ModelView.name(sp)
        dl = dims.space_dims(bm or ModelView({}), sp, "min_width", w) + (
            dims.space_dims(bm or ModelView({}), sp, "net_floor_area", a) if a is not None else [])
        txt = "; ".join(f"{p.label_en} {fmt(p.value, p.unit)} (min {fmt(p.limit, p.unit)})" for p in parts if p.value is not None) or "dimensions unknown"
        txt_tr = "; ".join(f"{p.label_tr} {fmt(p.value, p.unit)} (en az {fmt(p.limit, p.unit)})" for p in parts if p.value is not None) or "ölçüler bilinmiyor"
        out.append(env.finding(status, sp["guid"], f"{'Light well' if kind == 'light_well' else 'Air shaft'} '{nm}': {txt} [{label}]",
                               f"{'Işıklık' if kind == 'light_well' else 'Hava bacası'} '{nm}': {txt_tr}",
                               reason=reason, hint=hint, elements=[sp["guid"]] if source == "building_model" else [],
                               storey_id=sp.get("storey_id"), anchor=bm.anchor(sp) if bm and source == "building_model" else sp.get("anchor"),
                               measured=M(prim.value, prim.unit, prim.prov), required=R(prim.op, prim.limit, prim.unit),
                               dimensions=dl, source=source, view_id=sp.get("_view_id"),
                               extra={"parts": parts_extra(parts), "storeys": n}))
    return out
