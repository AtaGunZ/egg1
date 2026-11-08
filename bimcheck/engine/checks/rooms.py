"""Madde 29 (room minimum dimensions/areas) and Madde 32(1) (exterior light for living rooms/bedrooms)."""
from __future__ import annotations

from .. import dims
from ..finding import M, R, Env
from ..judge import Verdict, judge
from ..util import fmt, has_kw, min_rect, num, poly_area
from ..view import USAGE_EN, USAGE_TR, ModelView
from . import register
from .common import Part, get_spaces, merge_parts, need_building_model, parts_extra

# Madde 29(1) table: usage -> (min short side [m], min net area [m2] or None)
TABLE = {
    "living_room": (3.00, 12.00),
    "bedroom": (2.50, 9.00),
    "kitchen": (1.50, 3.30),
    "bathroom": (1.50, 3.00),
    "wc": (1.00, 1.20),
}
KITCHENETTE_AREA = 3.00  # "yemek pişirme yeri" / kitchen niche
KITCHEN_KW = ("mutfak", "kitchen", "kuche", "cocina", "cuisine", "kochen")
NICHE_KW = ("nisi", "nische", "niche", "kitchenette", "pantry", "yemek pisirme", "teekuche", "cooking")
WC_KW = ("wc", "tuvalet", "toilet", "wc/", "lavabo")


def _space_dim_values(bm: ModelView | None, sp: dict):
    """(min_width, prov, area, prov) with geometry fallbacks from the footprint."""
    ms = sp.get("measures") or {}
    pv = sp.get("provenance") or {}
    fp = ms.get("footprint")
    w, wp = num(ms.get("min_width")), pv.get("min_width")
    if w is None and fp:
        mr = min_rect(fp)
        if mr:
            w, wp = mr["short"], "geometry"
    a, ap = num(ms.get("net_floor_area")), pv.get("net_floor_area")
    if a is None and fp:
        a = poly_area(fp)
        ap = "geometry" if a is not None else None
    if a is None:
        a, ap = num(ms.get("gross_floor_area")), pv.get("gross_floor_area")
    return w, wp, a, ap


def requirement_for(env: Env, sp: dict) -> tuple[float, float | None, str]:
    """(min side, min area, note) for a space incl. combined-space summation rule (Madde 29(4))."""
    ms = sp.get("measures") or {}
    usage = ms.get("usage")
    table = dict(TABLE)
    for src in (env.params.get("table"), env.override.get("table")):
        if isinstance(src, list):
            src = {r.get("usage"): {"min_side": r.get("min_width"), "min_area": r.get("min_area")} for r in src if r.get("usage")}
        if isinstance(src, dict):
            for k, v in src.items():
                if isinstance(v, dict):
                    table[k] = (num(v.get("min_side")), num(v.get("min_area")))
                elif isinstance(v, (list, tuple)) and len(v) == 2:
                    table[k] = (num(v[0]), num(v[1]))
    side, area = table[usage]
    name = " ".join(str(x or "") for x in (sp.get("name"), sp.get("long_name")))
    note = ""
    if usage == "living_room" and has_kw(name, KITCHEN_KW):  # open-plan living+kitchen
        area = (area or 0) + (table["kitchen"][1] or 0)
        note = "living room combined with kitchen: areas are summed (Madde 29(4))"
    if usage == "bathroom" and has_kw(name, WC_KW):
        area = (area or 0) + (table["wc"][1] or 0)
        note = "bathroom combined with WC: areas are summed (Madde 29(4))"
    return side, area, note


@register("room_min_dims_area")
def room_min_dims_area(env: Env) -> list[dict]:
    spaces, source = get_spaces(env)
    if not spaces:
        return [env.na("No spaces/rooms available (need IFC spaces or drawing rooms)", "Mekân/oda verisi yok")]
    bm = env.bm
    sel = [s for s in spaces if (s.get("measures") or {}).get("usage") in TABLE]
    if not sel:
        return [env.na("No spaces with a Madde 29 usage (living room, bedroom, kitchen, bathroom, WC) were found",
                       "Madde 29 kapsamında kullanım sınıfı (oturma, yatak, mutfak, banyo, tuvalet) bulunan mekân yok",
                       source=source)]
    tol_w, tol_a = env.tol(0.005), 0.01
    results: list[tuple[dict, list[Part], str]] = []
    for sp in sel:
        usage = sp["measures"]["usage"]
        side, area, note = requirement_for(env, sp)
        w, wp, a, ap = _space_dim_values(bm, sp)
        usage_prov = (sp.get("provenance") or {}).get("usage")
        parts = []
        kw = dict(min_prov=env.min_provenance, semi=env.semi, exceptions=env.exceptions, legal=env.legal)
        parts.append(Part("min_width", "minimum side", "dar kenar", w, wp, ">=", side, "m",
                          judge(w, ">=", side, tol=tol_w, prov=wp, label="minimum side", **kw), note=note))
        if area is not None:
            parts.append(Part("net_floor_area", "net area", "net alan", a, ap, ">=", area, "m²",
                              judge(a, ">=", area, tol=tol_a, prov=ap, label="net area", **kw), note=note))
        results.append((sp, parts, note))
    # "1 bedroom of >= 9 m2" is a *minimum programme per dwelling*: a failing secondary room whose siblings on the
    # same storey comply is therefore only a review item (we cannot see dwelling boundaries in the model).
    ok_by_key: dict[tuple, int] = {}
    for sp, parts, _ in results:
        if all(p.verdict.status == "pass" for p in parts):
            k = (sp["measures"]["usage"], sp.get("storey_id"))
            ok_by_key[k] = ok_by_key.get(k, 0) + 1
    out = []
    for sp, parts, note in results:
        usage = sp["measures"]["usage"]
        status, reason, hint, prim = merge_parts(parts)
        if status == "violation" and source == "drawing_model":
            from ..view import dm_room_doubt
            doubt = dm_room_doubt(sp)
            if doubt:
                status, reason, hint = "review", "low_confidence", f"Drawing-derived value, but {doubt}. Verify on the drawing."
        if status == "violation" and ok_by_key.get((usage, sp.get("storey_id")), 0) > 0:
            status, reason = "review", "legal_judgement"
            hint = (f"Madde 29 requires at least ONE {USAGE_EN[usage].lower()} of this size per dwelling; another "
                    f"{USAGE_EN[usage].lower()} on this storey complies. Confirm this room is an additional one.")
        nm = ModelView.name(sp)
        subj_en, subj_tr = f"{USAGE_EN[usage]} '{nm}'", f"{USAGE_TR[usage]} '{nm}'"
        txt_en = "; ".join(f"{p.label_en} {fmt(p.value, p.unit)} (min {fmt(p.limit, p.unit)})" for p in parts if p.value is not None
                           ) or "dimensions unknown"
        txt_tr = "; ".join(f"{p.label_tr} {fmt(p.value, p.unit)} (en az {fmt(p.limit, p.unit)})" for p in parts if p.value is not None
                           ) or "ölçüler bilinmiyor"
        if note:
            txt_en += f" [{note}]"
        w_part = next(p for p in parts if p.key == "min_width")
        dl = dims.space_dims(bm or ModelView({}), sp, "min_width", w_part.value) if sp.get("measures", {}).get("footprint") else []
        a_part = next((p for p in parts if p.key == "net_floor_area"), None)
        if a_part is not None and a_part.value is not None:
            dl += dims.space_dims(bm or ModelView({}), sp, "net_floor_area", a_part.value)
        elif prim.value is None:
            pass
        guid_list = [sp["guid"]] if source == "building_model" else []
        f = env.finding(status, sp["guid"], f"{subj_en}: {txt_en}", f"{subj_tr}: {txt_tr}",
                        reason=reason, hint=hint, elements=guid_list, storey_id=sp.get("storey_id"),
                        anchor=(bm.anchor(sp) if bm and source == "building_model" else sp.get("anchor")),
                        measured=M(prim.value, prim.unit, prim.prov), required=R(prim.op, prim.limit, prim.unit),
                        dimensions=dl, source=source, view_id=sp.get("_view_id"),
                        extra={"parts": parts_extra(parts), "combined_note": note or None})
        out.append(f)
    return out


@register("living_room_exterior_light")
def living_room_exterior_light(env: Env) -> list[dict]:
    spaces, source = get_spaces(env)
    if not spaces:
        return [env.na("No spaces/rooms available", "Mekân/oda verisi yok")]
    bm = env.bm
    sel = [s for s in spaces if (s.get("measures") or {}).get("usage") in ("living_room", "bedroom")]
    if not sel:
        return [env.na("No living rooms or bedrooms found", "Oturma odası veya yatak odası bulunamadı", source=source)]
    out = []
    for sp in sel:
        ms = sp["measures"]
        usage = ms["usage"]
        nm = ModelView.name(sp)
        subj_en, subj_tr = f"{USAGE_EN[usage]} '{nm}'", f"{USAGE_TR[usage]} '{nm}'"
        has = ms.get("has_exterior_window")
        prov = (sp.get("provenance") or {}).get("has_exterior_window")
        req = {"op": "==", "value": True, "unit": ""}
        meas = {"value": has, "unit": "", "provenance": prov}
        base = dict(elements=[sp["guid"]] if source == "building_model" else [], storey_id=sp.get("storey_id"),
                    anchor=(bm.anchor(sp) if bm and source == "building_model" else sp.get("anchor")),
                    source=source, view_id=sp.get("_view_id"), measured=meas, required=req)
        wins = [bm.by_guid[g] for g in (ms.get("window_guids") or []) if bm and g in bm.by_guid]
        ext_wins = [w for w in wins if (w.get("measures") or {}).get("is_external") is not False]
        dl = []
        if bm and has and wins:
            w0 = (ext_wins or wins)[0]
            wm = w0.get("measures") or {}
            dl = dims.window_dims(bm, w0, num(wm.get("width")), None)
        ctx_el = [w["guid"] for w in (ext_wins or wins)[:4]]
        if has is None:
            out.append(env.review(sp["guid"], "missing_measure",
                                  "Whether this room has a window to the outside could not be derived - check the plan.",
                                  f"{subj_en}: exterior window presence unknown", f"{subj_tr}: dış cephe penceresi bilinmiyor",
                                  context_elements=ctx_el, dimensions=dl, **base))
        elif has:
            out.append(env.finding("pass", sp["guid"], f"{subj_en}: has a direct exterior window",
                                   f"{subj_tr}: doğrudan dış cepheye açılan penceresi var", context_elements=ctx_el,
                                   dimensions=dl, **base))
        elif prov == "inferred":
            out.append(env.review(sp["guid"], "low_confidence",
                                  "No exterior window was found, but the result is inferred - check the plan.",
                                  f"{subj_en}: no direct exterior window found (inferred)",
                                  f"{subj_tr}: doğrudan dış cephe penceresi bulunamadı (tahmin)", context_elements=ctx_el,
                                  **base))
        else:
            en = f"{subj_en}: no direct exterior window (Madde 32(1): living rooms and bedrooms need direct light and air from outside)"
            tr = f"{subj_tr}: doğrudan dış cepheye açılan pencere yok (Madde 32(1))"
            out.append(env.finding("violation", sp["guid"], en, tr, context_elements=ctx_el, **base))
    return out
