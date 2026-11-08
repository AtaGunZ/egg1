"""Madde 39 (door dimensions) and Madde 38 (guards at low window sills / railing height)."""
from __future__ import annotations

from .. import dims
from ..finding import Env, M, R, describe
from ..judge import Verdict, judge, judge_two, worst
from ..util import dim, fmt, has_kw, num
from ..view import USAGE_EN, ModelView
from . import register
from .common import need_building_model

DOUBLE_KW = ("double", "cift", "doppel", "zweifl", "2-flg", "2 flg", "two leaf", "2-leaf", "double-leaf")
HANDRAIL_KW = ("handrail", "kupeste", "handlauf", "hand rail", "grab")


def _door_text(el: dict) -> str:
    p = el.get("props") or {}
    return " ".join(str(x) for x in (el.get("name"), el.get("object_type"), el.get("long_name"),
                                     p.get("OperationType"), p.get("Reference"), p.get("PredefinedType")) if x)


def double_leaf(el: dict) -> bool | None:
    p = el.get("props") or {}
    n = num(p.get("NumberOfLeaves") or p.get("LeafCount") or (el.get("measures") or {}).get("leaf_count"))
    if n is not None:
        return n >= 2
    op = str(p.get("OperationType") or "")
    if "DOUBLE" in op.upper():
        return True
    if op and "SINGLE" in op.upper():
        return False
    if has_kw(_door_text(el), DOUBLE_KW):
        return True
    return None


def classify_door(env: Env, d: dict) -> tuple[str, str]:
    """(class, why) - class in balcony|wc|bathroom|building_entrance|entrance_candidate|dwelling_entrance|other."""
    bm = env.bm
    ms = d.get("measures") or {}
    sp = [bm.by_guid.get(g) for g in (ms.get("space_guids") or [])]
    usages = {(s.get("measures") or {}).get("usage") for s in sp if s}
    if usages & {"balcony", "terrace"}:
        return "balcony", "connects to a balcony/terrace"
    if "wc" in usages:
        return "wc", "connects to a WC"
    if ms.get("is_entrance") is True:
        return "building_entrance", "marked as building entrance"
    ext = ms.get("is_external")
    if ext is True:
        if ms.get("is_entrance") is False:
            return "other", "external door that is not an entrance"
        return "entrance_candidate", "external door"
    if "stair" in usages:
        return "dwelling_entrance", "opens from a stair room"
    if "bathroom" in usages:
        return "bathroom", "connects to a bathroom"
    return "other", "interior door"


@register("door_dimensions")
def door_dimensions(env: Env) -> list[dict]:
    na = need_building_model(env, "doors")
    if na:
        return na
    bm = env.bm
    doors = bm.of_kind("door")
    if not doors:
        return [env.na("No doors in the model", "Modelde kapı yok")]
    tol = env.tol(0.005)
    h_min = env.params.get("min_height", 2.10)
    n_storeys = bm.storey_counts()["total"]
    single = env.ctx.get("is_single_dwelling")
    scope = env.params.get("scope")
    out = []
    for d in doors:
        ms = d.get("measures") or {}
        pv = d.get("provenance") or {}
        w, wp = num(ms.get("width")), pv.get("width")
        h, hp = num(ms.get("height")), pv.get("height")
        if ms.get("width_kind") == "overall" and wp in ("property", "quantity"):
            wp = "geometry"  # overall frame width, clear width is smaller: near-limit passes need a human
        cls, why = classify_door(env, d)
        if scope == "balcony_door" and cls != "balcony":
            continue
        if scope == "width" and cls == "building_entrance":
            continue  # building entrances are handled by the declarative 1.50 m rule
        nm = ModelView.name(d)
        subj_en, subj_tr = f"Door '{nm}'", f"Kapı '{nm}'"
        kw = dict(tol=tol, min_prov=env.min_provenance or "property", semi=env.semi, exceptions=env.exceptions,
                  legal=env.legal)
        lim_note = ""
        w_eval = w
        if env.overridden("limit"):
            lim = env.limit("limit")
            vw, lim_note = judge(w, ">=", lim, prov=wp, label="clear width", **kw), "project override"
        elif cls == "balcony" and scope == "balcony_door":
            lim, lim_note = 0.90, "balcony door, 4-9 storeys (Madde 39(5))"
            vw = judge(w, ">=", lim, prov=wp, label="clear width", **kw)
            if vw.status == "violation":
                vw = Verdict("review", "legal_judgement",
                             "At least ONE balcony door per dwelling must be 0.90 m net; dwelling grouping is not available - "
                             "confirm that another balcony door of this dwelling complies.", False)
        elif cls == "balcony" and scope == "width":
            lim, lim_note = 0.80, "balcony door"
            vw = judge(w, ">=", lim, prov=wp, label="clear width", **kw)
        elif cls == "balcony":
            if 3 < n_storeys < 10:
                vw, which = judge_two(w, ">=", 0.90, 0.80, reason="legal_judgement",
                                      hint="Balcony doors may be 0.80 m, but in buildings of 4-9 storeys at least one balcony door "
                                           "per dwelling must be 0.90 m net (Madde 39(5)) - confirm.", prov=wp,
                                      label="clear width", **kw)
                lim = 0.90 if which == "strict" else 0.80
            else:
                lim = 0.80
                vw = judge(w, ">=", lim, prov=wp, label="clear width", **kw)
            lim_note = "balcony door"
        elif cls == "wc":
            lim = 0.80
            vw, lim_note = judge(w, ">=", lim, prov=wp, label="clear width", **kw), "WC door"
        elif cls == "bathroom":
            vw, which = judge_two(w, ">=", 0.90, 0.80, reason="legal_judgement",
                                  hint="0.80 m is allowed for WC doors only; if this door serves a separate WC it complies, "
                                       "a bathroom door must be 0.90 m.", prov=wp, label="clear width", **kw)
            lim = 0.90 if which == "strict" else 0.80
            lim_note = "bathroom door"
        elif cls == "building_entrance":
            dl = double_leaf(d)
            if single is True:
                lim, lim_note = 1.00, "entrance of a single dwelling"
                vw = judge(w, ">=", lim, prov=wp, label="clear width", **kw)
            elif dl is True:
                w_eval = None if w is None else w / 2.0
                lim, lim_note = 1.00, "building entrance, double-leaf: one leaf"
                vw = judge(w_eval, ">=", lim, prov=wp, label="leaf width", **kw)
            elif dl is None and w is not None and 1.50 - tol <= w < 2.00 - tol:
                vw = Verdict("review", "missing_context",
                             "Door leaf count unknown: a single-leaf 1.50 m door is fine, but a double-leaf door needs one leaf >= 1.00 m "
                             "(Madde 39(1)b).", None)
                lim, lim_note = 1.50, "building entrance"
            else:
                lim, lim_note = 1.50, "building entrance"
                vw = judge(w, ">=", lim, prov=wp, label="clear width", **kw)
        elif cls == "entrance_candidate":
            vw, which = judge_two(w, ">=", 1.50 if single is not True else 1.00, 0.90, reason="missing_context",
                                  hint="External door whose role is unknown: building entrance needs 1.50 m (double-leaf: one leaf 1.00 m), "
                                       "dwelling entrance 1.00 m, other doors 0.90 m. Set is_entrance on the door.",
                                  prov=wp, label="clear width", **kw)
            lim = (1.50 if single is not True else 1.00) if which == "strict" else 0.90
            lim_note = "external door - role unclear"
        elif cls == "dwelling_entrance":
            lim, lim_note = 1.00, "dwelling entrance"
            vw = judge(w, ">=", lim, prov=wp, label="clear width", **kw)
        else:
            lim, lim_note = 0.90, "interior/other door"
            vw = judge(w, ">=", lim, prov=wp, label="clear width", **kw)
        vh = (judge(h, ">=", h_min, tol=tol, prov=hp, min_prov=env.min_provenance, semi=env.semi, label="height")
              if scope not in ("width", "balcony_door") else Verdict("pass", ok=True))
        status = worst(vw.status, vh.status)
        pick = vw if vw.status == status else vh
        if status == "pass":
            pick = vw
        en_w = (f"clear width {fmt(w, 'm')} (min {fmt(lim, 'm')}, {lim_note})" if w is not None else "clear width unknown")
        en_h = (f"height {fmt(h, 'm')} (min {fmt(h_min, 'm')})" if h is not None else "height unknown")
        if scope in ("width", "balcony_door"):
            en_h = "-"
        tr_w = (f"net genişlik {fmt(w, 'm')} (en az {fmt(lim, 'm')})" if w is not None else "net genişlik bilinmiyor")
        tr_h = (f"yükseklik {fmt(h, 'm')} (en az {fmt(h_min, 'm')})" if h is not None else "yükseklik bilinmiyor")
        hint = pick.hint if status == "review" else None
        if status == "review" and vw.status == "review" and vh.status == "review":
            hint = " ".join(x for x in (vw.hint, vh.hint) if x)
        primary_is_h = (pick is vh)
        meas = M(h, "m", hp) if primary_is_h else M(w, "m", wp)
        req = R(">=", h_min, "m") if primary_is_h else R(">=", lim, "m")
        full_en = f"{subj_en}: {en_w}" + ("" if en_h == "-" else f"; {en_h}")
        full_tr = f"{subj_tr}: {tr_w}" + ("" if en_h == "-" else f"; {tr_h}")
        out.append(env.finding(status, d["guid"], full_en, full_tr,
                               reason=pick.reason, hint=hint, elements=[d["guid"]], storey_id=d.get("storey_id"),
                               anchor=bm.anchor(d), measured=meas, required=req,
                               dimensions=dims.door_dims(bm, d, w, h),
                               context_elements=list(ms.get("space_guids") or [])[:3],
                               extra={"door_class": cls, "door_class_why": why}))
    return out


# ------------------------------------------------------------------------------------- guards
def _bbox_overlap(a: dict, b: dict, pad: float, check_z: bool = False) -> bool:
    for i in (0, 1) + ((2,) if check_z else ()):
        if a["max"][i] + pad < b["min"][i] or b["max"][i] + pad < a["min"][i]:
            return False
    return True


def _railing_height(r: dict) -> tuple[float | None, str | None]:
    h = num((r.get("measures") or {}).get("height"))
    if h is not None:
        return h, (r.get("provenance") or {}).get("height")
    bb = r.get("bbox")
    if bb:
        return bb["max"][2] - bb["min"][2], "geometry"
    return None, None


@register("window_sill_guard")
def window_sill_guard(env: Env) -> list[dict]:
    na = need_building_model(env, "windows and railings")
    if na:
        return na
    bm = env.bm
    wins, rails = bm.of_kind("window"), bm.of_kind("railing")
    if not wins and not rails:
        return [env.na("No windows or railings in the model", "Modelde pencere veya korkuluk yok")]
    tol = env.tol(0.005)
    g_min = env.limit("limit") if env.overridden("limit") else float(env.params.get("guard_height", 1.10))
    sill_max = float(env.params.get("sill_max", 0.90))
    out = []
    for w in wins:
        ms = w.get("measures") or {}
        sill, sp = num(ms.get("sill_height")), (w.get("provenance") or {}).get("sill_height")
        nm = ModelView.name(w)
        subj_en, subj_tr = f"Window '{nm}'", f"Pencere '{nm}'"
        base = dict(elements=[w["guid"]], storey_id=w.get("storey_id"), anchor=bm.anchor(w))
        if sill is None:
            out.append(env.review(w["guid"], "missing_measure", "Sill height not available - check whether a guard is needed.",
                                  f"{subj_en}: sill height unknown", f"{subj_tr}: denizlik yüksekliği bilinmiyor",
                                  dimensions=dims.window_dims(bm, w, None, None), **base))
            continue
        dl = dims.window_dims(bm, w, num(ms.get("width")), sill)
        if sill >= sill_max - tol:
            if sp == "inferred" and abs(sill - sill_max) <= 0.05 * sill_max:
                out.append(env.review(w["guid"], "low_confidence", "Sill height is inferred and close to 0.90 m - verify.",
                                      f"{subj_en}: sill {fmt(sill, 'm')} is close to the 0.90 m limit (inferred)",
                                      f"{subj_tr}: denizlik {fmt(sill, 'm')} 0.90 m sınırına yakın (tahmin)",
                                      measured=M(sill, "m", sp), required=R(">=", sill_max, "m"), dimensions=dl, **base))
            else:
                out.append(env.finding("pass", w["guid"], f"{subj_en}: sill {fmt(sill, 'm')} >= {fmt(sill_max, 'm')}, no guard needed",
                                       f"{subj_tr}: denizlik {fmt(sill, 'm')} >= {fmt(sill_max, 'm')}, korkuluk gerekmez",
                                       measured=M(sill, "m", sp), required=R(">=", sill_max, "m"), dimensions=dl, **base))
            continue
        wb = w.get("bbox")
        near = []
        if wb:
            for r in rails:
                rb = r.get("bbox")
                if rb and (r.get("storey_id") == w.get("storey_id") or not r.get("storey_id") or not w.get("storey_id")) \
                        and _bbox_overlap(wb, rb, 0.6):
                    near.append(r)
        if near:
            best_h, best_r, best_p = None, None, None
            for r in near:
                h, p = _railing_height(r)
                if h is not None and (best_h is None or h > best_h):
                    best_h, best_r, best_p = h, r, p
            if best_h is not None:
                v = judge(best_h, ">=", g_min, tol=tol, prov=best_p, min_prov=env.min_provenance, semi=env.semi,
                          label="guard height")
                rb = best_r["bbox"]
                cx, cy = (rb["min"][0] + rb["max"][0]) / 2, (rb["min"][1] + rb["max"][1]) / 2
                floor = rb["min"][2]
                dl2 = dl + [dim([cx, cy, floor], [cx, cy, floor + best_h], f"guard {fmt(best_h, 'm')}", "clearance")]
                en = (f"{subj_en}: sill {fmt(sill, 'm')} < {fmt(sill_max, 'm')}; guard '{ModelView.name(best_r)}' is "
                      f"{fmt(best_h, 'm')} high (min {fmt(g_min, 'm')})")
                tr = (f"{subj_tr}: denizlik {fmt(sill, 'm')} < {fmt(sill_max, 'm')}; korkuluk '{ModelView.name(best_r)}' "
                      f"yüksekliği {fmt(best_h, 'm')} (en az {fmt(g_min, 'm')})")
                out.append(env.from_verdict(v, w["guid"], en, tr, measured=M(best_h, "m", best_p), required=R(">=", g_min, "m"),
                                            dimensions=dl2, context_elements=[best_r["guid"]], **base))
                continue
        out.append(env.review(w["guid"], "missing_measure",
                              "Low sill but no railing found next to the window. Check whether the window has a built-in guard / "
                              "fixed glazing >= 1.10 m, or whether there is no fall hazard (ground-floor window).",
                              f"{subj_en}: sill {fmt(sill, 'm')} is below {fmt(sill_max, 'm')} and no guard (>= {fmt(g_min, 'm')}) was found",
                              f"{subj_tr}: denizlik {fmt(sill, 'm')} < {fmt(sill_max, 'm')} ve korkuluk (>= {fmt(g_min, 'm')}) bulunamadı",
                              measured=M(sill, "m", sp), required=R(">=", sill_max, "m"), dimensions=dl, **base))
    return out
