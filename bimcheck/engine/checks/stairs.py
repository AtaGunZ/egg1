"""Madde 31 - stairs: riser vs lift, tread formula, width."""
from __future__ import annotations

from .. import dims
from ..finding import Env, M, R, describe
from ..judge import Verdict, judge, judge_two, worst
from ..util import dim, fmt, has_kw, num
from ..view import ModelView
from . import register
from .common import need_building_model

EXTERNAL_KW = ("external", "exterior", "outdoor", "outside", "dis merdiven", "außen", "aussen", "yangin merdiveni", "fire escape")
INTERNAL_KW = ("interior", "internal", "dwelling", "daire ici", "maisonette", "ic merdiven")
COMMON_KW = ("common", "ortak", "main stair", "ana merdiven", "fire", "escape", "yangin", "treppenhaus", "emergency")
SPECIAL_KW = ("winder", "spiral", "balans", "helical", "curved", "wendel", "spindel")


def _stair_text(el: dict) -> str:
    props = el.get("props") or {}
    return " ".join(str(x) for x in (el.get("name"), el.get("long_name"), el.get("object_type"),
                                     props.get("PredefinedType"), props.get("Reference")) if x)


def is_external_stair(el: dict) -> bool | None:
    v = (el.get("props") or {}).get("IsExternal")
    if v is None:
        v = (el.get("measures") or {}).get("is_external")
    if v is not None:
        return bool(v)
    if has_kw(_stair_text(el), EXTERNAL_KW):
        return True
    return None


def lift_status(env: Env) -> tuple[bool | None, str]:
    """(has_lift, source) with source in context|model|inferred|unknown."""
    c = env.ctx.get("has_elevator")
    if c is not None:
        return bool(c), "context"
    if env.bm:
        ev, _ = env.bm.lift_evidence()
        if ev == "element":
            return True, "model"
        if env.bm.storey_counts()["total"] >= 4:
            return True, "inferred"
    return None, "unknown"


def _stair_common(env: Env, st: dict, measure: str):
    bm = env.bm
    val = bm.measure(st, measure)
    return num(val), bm.prov(st, measure)


def _base(env: Env, st: dict) -> dict:
    bm = env.bm
    return dict(elements=[st["guid"]], storey_id=st.get("storey_id"), anchor=bm.anchor(st))


@register("stair_riser_vs_elevator")
def stair_riser_vs_elevator(env: Env) -> list[dict]:
    na = need_building_model(env, "stairs")
    if na:
        return na
    bm = env.bm
    stairs = bm.of_kind("stair")
    if not stairs:
        return [env.na("No stairs in the model", "Modelde merdiven yok")]
    lift, src = lift_status(env)
    tol = env.tol(0.005)
    out = []
    for st in stairs:
        riser, prov = _stair_common(env, st, "riser_height")
        nm = ModelView.name(st)
        ext = is_external_stair(st)
        subj_en, subj_tr = f"Stair '{nm}'", f"Merdiven '{nm}'"
        kw = dict(tol=tol, prov=prov, min_prov=env.min_provenance, semi=env.semi, exceptions=env.exceptions,
                  legal=env.legal, label="riser height")
        if env.overridden("limit"):
            lim, case = env.limit("limit"), "project override"
            v, which = judge(riser, "<=", lim, **kw), "strict"
        elif ext:
            lim, case = 0.15, "external stair"
            v, which = judge(riser, "<=", lim, **kw), "strict"
        elif lift is True and src in ("context", "model"):
            lim, case = 0.18, "building has a lift"
            v, which = judge(riser, "<=", lim, **kw), "strict"
        elif lift is False and src == "context":
            lim, case = 0.16, "building without lift"
            v, which = judge(riser, "<=", lim, **kw), "strict"
        elif lift is True:  # inferred from storey count
            lim, case = 0.16, "lift assumed (>=4 storeys, Madde 34) - not confirmed"
            v, which = judge_two(riser, "<=", 0.16, 0.18, reason="low_confidence",
                                 hint="Riser is between 0.16 m and 0.18 m: allowed only if the building really has a lift. "
                                      "No lift is modelled; the lift was inferred from the storey count - confirm "
                                      "(or set has_elevator in the project context).", **kw)
            lim = 0.16 if which == "strict" else 0.18
        else:
            lim, case = 0.16, "lift status unknown"
            v, which = judge_two(riser, "<=", 0.16, 0.18, reason="missing_context",
                                 hint="Riser is between 0.16 m and 0.18 m: allowed only if the building has a lift - "
                                      "set has_elevator in the project context.", **kw)
            lim = 0.16 if which == "strict" else 0.18
        en, tr = describe(subj_en, subj_tr, "riser height", "basamak yüksekliği", riser, "m", "<=", lim)
        en += f" ({case})"
        out.append(env.from_verdict(v, st["guid"], en, tr, measured=M(riser, "m", prov), required=R("<=", lim, "m"),
                                    dimensions=dims.stair_dims(bm, st, "riser_height", riser), **_base(env, st)))
    return out


def _unusual_stair(st: dict) -> bool:
    return has_kw(_stair_text(st), SPECIAL_KW)


@register("stair_tread_formula")
def stair_tread_formula(env: Env) -> list[dict]:
    na = need_building_model(env, "stairs")
    if na:
        return na
    bm = env.bm
    stairs = bm.of_kind("stair")
    if not stairs:
        return [env.na("No stairs in the model", "Modelde merdiven yok")]
    tol = env.tol(0.005)
    lo = float(env.params.get("formula_min", 0.60))
    hi = float(env.params.get("formula_max", 0.64))
    min_tread = float(env.override.get("limit", env.params.get("min_tread", 0.27)))
    out = []
    for st in stairs:
        a, pa = _stair_common(env, st, "riser_height")
        b, pb = _stair_common(env, st, "tread_depth")
        nm = ModelView.name(st)
        subj_en, subj_tr = f"Stair '{nm}'", f"Merdiven '{nm}'"
        prov = pb if (pa is None or (pb is not None and pb == "inferred")) else pa
        if "inferred" in (pa, pb):
            prov = "inferred"
        base = _base(env, st)
        dlist = dims.stair_dims(bm, st, "riser_height", a) + dims.stair_dims(bm, st, "tread_depth", b)
        if a is None or b is None:
            out.append(env.review(st["guid"], "missing_measure",
                                  "Riser height and tread depth are both needed for 2a+b; measure them on the stair section.",
                                  f"{subj_en}: riser/tread not available - 2a+b cannot be evaluated",
                                  f"{subj_tr}: basamak yüksekliği/genişliği bulunamadı - 2a+b hesaplanamadı",
                                  measured=M(None, "m", None), required=R("range", lo, "m", hi), dimensions=dlist, **base))
            continue
        f = 2 * a + b
        kw = dict(tol=tol, prov=prov, min_prov=env.min_provenance, semi=env.semi)
        v_f = judge(f, "range", lo, limit_max=hi, label="2a+b", **kw)
        v_t = judge(b, ">=", min_tread, label="tread depth", **kw)
        status = worst(v_f.status, v_t.status)
        if _unusual_stair(st) and status == "violation":
            v = Verdict("review", "legal_judgement",
                        "Winder/spiral/balanced stairs follow Madde 31(2)c (0.10 m at the narrow end, 0.27 m mid-tread), "
                        "not the straight-flight formula - check manually.", False)
        else:
            v = v_f if v_f.status == status else v_t
        en = (f"{subj_en}: 2a+b = {fmt(f, 'm')} (riser {fmt(a, 'm')}, tread {fmt(b, 'm')}); required "
              f"{fmt(lo, 'm')} - {fmt(hi, 'm')} and tread >= {fmt(min_tread, 'm')}")
        tr = (f"{subj_tr}: 2a+b = {fmt(f, 'm')} (yükseklik {fmt(a, 'm')}, genişlik {fmt(b, 'm')}); gereken "
              f"{fmt(lo, 'm')} - {fmt(hi, 'm')} ve genişlik >= {fmt(min_tread, 'm')}")
        out.append(env.from_verdict(v, st["guid"], en, tr, measured=M(f, "m", prov), required=R("range", lo, "m", hi),
                                    dimensions=dlist, extra={"riser": a, "tread": b, "min_tread": min_tread}, **base))
    return out


def classify_stair(env: Env, st: dict) -> str:
    """'internal' (inside a dwelling), 'common' or 'unknown'."""
    if env.ctx.get("is_single_dwelling") is True:
        return "internal"
    t = _stair_text(st)
    if has_kw(t, INTERNAL_KW):
        return "internal"
    if has_kw(t, COMMON_KW):
        return "common"
    return "unknown"


@register("stair_width")
def stair_width(env: Env) -> list[dict]:
    na = need_building_model(env, "stairs")
    if na:
        return na
    bm = env.bm
    stairs = bm.of_kind("stair")
    if not stairs:
        return [env.na("No stairs in the model", "Modelde merdiven yok")]
    tol = env.tol(0.005)
    use = env.use or "residential"
    resid = use in ("residential", "mixed")
    common_lim = 1.20 if resid else 1.50
    out = []
    for st in stairs:
        w, prov = _stair_common(env, st, "width")
        cls = classify_stair(env, st)
        nm = ModelView.name(st)
        subj_en, subj_tr = f"Stair '{nm}'", f"Merdiven '{nm}'"
        kw = dict(tol=tol, prov=prov, min_prov=env.min_provenance, semi=env.semi, exceptions=env.exceptions,
                  legal=env.legal, label="stair width")
        if env.overridden("limit"):
            lim, case = env.limit("limit"), "project override"
            v = judge(w, ">=", lim, **kw)
        elif cls == "internal":
            lim, case = 1.00, "stair inside a dwelling"
            v = judge(w, ">=", lim, **kw)
        elif cls == "common":
            lim, case = common_lim, "common stair" + ("" if resid else ", non-residential")
            v = judge(w, ">=", lim, **kw)
        else:
            loose = 1.00 if resid else 1.20
            v, which = judge_two(w, ">=", common_lim, loose, reason="missing_context",
                                 hint=("Cannot tell whether this is a common stair (min %.2f m) or a stair inside a dwelling (min 1.00 m) "
                                       "- classify it, or set is_single_dwelling in the project context." % common_lim) if resid else
                                 ("Cannot tell whether this is a common stair (min 1.50 m) or one serving a shop under 100 m2 (min 1.20 m)."),
                                 **kw)
            lim = common_lim if which == "strict" else loose
            case = "classification unknown"
        if v.status == "violation" and _unusual_stair(st):
            v = Verdict("review", "legal_judgement",
                        "Spiral/winder stairs are governed by Madde 31(2)c; check whether this stair is an allowed in-dwelling stair "
                        "and its required width.", False)
        en, tr = describe(subj_en, subj_tr, "width", "genişlik", w, "m", ">=", lim)
        en += f" ({case})"
        out.append(env.from_verdict(v, st["guid"], en, tr, measured=M(w, "m", prov), required=R(">=", lim, "m"),
                                    dimensions=dims.stair_dims(bm, st, "width", w), extra={"stair_class": cls},
                                    **_base(env, st)))
    return out
