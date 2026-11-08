"""Declarative evaluator: check.type = min | max | range | equals | exists."""
from __future__ import annotations

import re
from typing import Any

from . import dims
from .finding import Env, M, R, describe, label_for, unit_for
from .judge import compare, judge
from .util import fold, min_rect, num, poly_area
from .view import KIND_EN, KIND_TR, USAGE_EN, USAGE_TR, ModelView

_OPS = ("==", "!=", ">=", "<=", ">", "<", "=")
_PRED_RE = re.compile(r"^\s*([\w.]+)\s*(==|!=|>=|<=|>|<|=)\s*(.+?)\s*$")


# ----------------------------------------------------------------------------- value access
def measure_value(view: ModelView | None, el: dict, name: str) -> tuple[Any, str | None]:
    """(value, provenance) for a measure name: measures > props > derived-from-geometry."""
    ms = el.get("measures") or {}
    if name in ms and ms[name] is not None:
        return ms[name], (el.get("provenance") or {}).get(name)
    props = el.get("props") or {}
    if name in props and props[name] is not None:
        return props[name], "property"
    kind = el.get("kind")
    if kind == "space":
        fp = ms.get("footprint")
        if name in ("net_floor_area", "area"):
            a = ms.get("net_floor_area")
            if a is None:
                a = poly_area(fp)
                if a is not None:
                    return a, "geometry"
            return a, (el.get("provenance") or {}).get("net_floor_area")
        if name in ("min_width", "max_length") and fp:
            mr = min_rect(fp)
            if mr:
                return (mr["short"] if name == "min_width" else mr["long"]), "geometry"
        if name == "height":
            fz, cz = num(ms.get("floor_z")), num(ms.get("ceiling_z"))
            if fz is not None and cz is not None and cz > fz:
                return cz - fz, "geometry"
    if name in el and not isinstance(el[name], (dict, list)):
        return el[name], None
    return None, None


def _coerce(s: str) -> Any:
    t = s.strip().strip("'\"")
    low = t.lower()
    if low in ("true", "yes"):
        return True
    if low in ("false", "no"):
        return False
    if low in ("null", "none"):
        return None
    try:
        return float(t)
    except ValueError:
        return t


def _eq(a: Any, b: Any) -> bool:
    if isinstance(b, bool) or isinstance(a, bool):
        return bool(a) == bool(b) if a is not None else False
    na, nb = num(a), num(b)
    if na is not None and nb is not None:
        return abs(na - nb) < 1e-9
    return fold(a) == fold(b)


def _apply_op(a: Any, op: str, b: Any) -> bool:
    if op in ("==", "="):
        return _eq(a, b)
    if op == "!=":
        return not _eq(a, b)
    na, nb = num(a), num(b)
    if na is None or nb is None:
        return False
    return compare(na, op if op != "=" else "==", nb, 0.0)


def match_where(view: ModelView | None, el: dict, where: Any) -> bool:
    """Simple predicate on measures/props. Forms: 'a == true and b >= 1.2' | {k: v} | {k: {'>=': 1}} |
    {'measure':k,'op':'>=','value':v} | list (AND)."""
    if not where:
        return True
    if isinstance(where, str):
        for part in re.split(r"\s+and\s+|&&", where, flags=re.I):
            m = _PRED_RE.match(part)
            if not m:
                raise ValueError(f"cannot parse where-predicate {part!r}")
            key, op, val = m.group(1), m.group(2), _coerce(m.group(3))
            if not _apply_op(measure_value(view, el, key)[0], op, val):
                return False
        return True
    if isinstance(where, list):
        return all(match_where(view, el, w) for w in where)
    if isinstance(where, dict):
        if "measure" in where and "op" in where:
            return _apply_op(measure_value(view, el, where["measure"])[0], where["op"], where.get("value"))
        for key, cond in where.items():
            val = measure_value(view, el, key)[0]
            if isinstance(cond, dict):
                for op, ref in cond.items():
                    if op == "in":
                        if not any(_eq(val, r) for r in ref):
                            return False
                    elif not _apply_op(val, op, ref):
                        return False
            elif isinstance(cond, list):
                if not any(_eq(val, c) for c in cond):
                    return False
            elif not _eq(val, cond):
                return False
        return True
    raise ValueError(f"unsupported where-predicate type {type(where).__name__}")


# ----------------------------------------------------------------------------- limit_by
def _lookup_value(env: Env, el: dict, name: str) -> Any:
    v, _ = measure_value(env.bm, el, name)
    if v is not None:
        return v
    if name in ("stair_has_elevator", "has_elevator"):
        c = env.ctx.get("has_elevator")
        if c is not None:
            return bool(c)
        if env.bm:
            ev, _ = env.bm.lift_evidence()
            if ev == "element":
                return True
        return None
    if name == "use" or name == "building_use":
        return env.use
    if name == "storey_count" and env.bm:
        return env.bm.storey_counts()["total"]
    return env.ctx.get(name)


def resolve_limit(env: Env, el: dict | None) -> tuple[float | None, float | None, str | None]:
    """(limit, limit_max, note). Override wins; then limit_by; then plain limit. Base units."""
    chk = env.check
    lim = env.limit("limit")
    lim_max = env.limit("limit_max")
    note = None
    if env.overridden("limit"):
        return lim, lim_max, "overridden"
    lb = chk.get("limit_by")
    if lb and el is not None:
        raw = _lookup_value(env, el, lb.get("measure", ""))
        mp = lb.get("map") or {}
        if raw is not None:
            key = str(raw).lower() if not isinstance(raw, bool) else ("true" if raw else "false")
            if key in mp:
                return env_to_base(env, mp[key]), lim_max, f"{lb.get('measure')}={key}"
            for k, v in mp.items():  # case/diacritic-insensitive
                if fold(k) == fold(key):
                    return env_to_base(env, v), lim_max, f"{lb.get('measure')}={key}"
        if "default" in lb and lb["default"] is not None:
            return env_to_base(env, lb["default"]), lim_max, f"{lb.get('measure')}=unknown (default)"
        if lim is not None:
            return lim, lim_max, None
        return None, lim_max, f"limit_by value for '{lb.get('measure')}' is unknown"
    return lim, lim_max, note


def env_to_base(env: Env, v: Any) -> float | None:
    from .util import to_base
    return to_base(v, env.unit)


# ----------------------------------------------------------------------------- evaluation
def _op_for(chk: dict) -> str:
    t = chk.get("type")
    op = chk.get("op")
    if op:
        return {"≥": ">=", "≤": "<=", "=": "=="}.get(op, op)
    return {"min": ">=", "max": "<=", "equals": "==", "range": "range"}.get(t, ">=")


def select_targets(env: Env) -> tuple[list[dict], str]:
    """Candidate elements for the rule target; returns (elements, source) where source is
    'building_model' or 'drawing_model'."""
    tgt = env.check.get("target") or {}
    kind = tgt.get("kind")
    bm, dm = env.bm, env.dm
    elements: list[dict] = []
    source = "building_model"
    if bm and kind:
        elements = list(bm.of_kind(kind))
    if (not elements) and kind == "space" and dm and dm.rooms:
        elements = [dm.room_as_space(r) for r in dm.rooms]
        source = "drawing_model"
    usage_in, usage_not = tgt.get("usage_in"), tgt.get("usage_not_in")
    sk = (env.rule.get("applies_when") or {}).get("storey_kind")
    out = []
    rev = _usage_index(bm) if (bm and kind != "space" and (usage_in or usage_not)) else {}
    for e in elements:
        if kind == "space":
            u = (e.get("measures") or {}).get("usage")
            if usage_in and u not in usage_in:
                continue
            if usage_not and u in usage_not:
                continue
        elif usage_in or usage_not:
            us = rev.get(e.get("guid"), set())
            for g in (e.get("measures") or {}).get("space_guids") or []:
                sp = bm.by_guid.get(g)
                if sp:
                    us.add((sp.get("measures") or {}).get("usage"))
            if not us:
                continue  # serving space unknown -> cannot tell whether the rule targets it
            if usage_in and not (us & set(usage_in)):
                continue
            if usage_not and (us & set(usage_not)):
                continue
        if sk and source == "building_model" and bm:
            if not bm.matches_storey_kind(bm.storey_of(e), sk):
                continue
        if tgt.get("where") and not match_where(bm, e, tgt["where"]):
            continue
        out.append(e)
    return out, source


def _usage_index(bm: ModelView) -> dict[str, set]:
    """element guid -> usages of spaces that list it as window/door."""
    idx: dict[str, set] = {}
    for sp in bm.of_kind("space"):
        u = (sp.get("measures") or {}).get("usage")
        for key in ("window_guids", "door_guids"):
            for g in (sp.get("measures") or {}).get(key) or []:
                idx.setdefault(g, set()).add(u)
    return idx


def _subject(view: ModelView, el: dict) -> tuple[str, str]:
    kind = el.get("kind") or "other"
    ms = el.get("measures") or {}
    if kind == "space" and ms.get("usage") in USAGE_EN:
        en, tr = USAGE_EN[ms["usage"]], USAGE_TR[ms["usage"]]
    else:
        en, tr = KIND_EN.get(kind, "Element"), KIND_TR.get(kind, "Eleman")
    nm = ModelView.name(el)
    return f"{en} '{nm}'", f"{tr} '{nm}'"


def default_tolerance(unit: str) -> float:
    return {"m": 0.005, "m²": 0.01}.get(unit, 0.0)


def evaluate_element(env: Env, el: dict, source: str, *, key: str | None = None) -> dict:
    chk = env.check
    ctype = chk.get("type")
    measure = chk.get("measure")
    view = env.bm
    value, prov = measure_value(view, el, measure) if measure else (None, None)
    unit = unit_for(measure or "", env.unit) if measure else base_unit_of(env)
    en_l, tr_l, _ = label_for(measure or "")
    if measure == "height" and el.get("kind") != "space":
        en_l, tr_l = "height", "yükseklik"
    subj_en, subj_tr = _subject(view or ModelView({}), el)
    op = _op_for(chk)
    limit, limit_max, lnote = resolve_limit(env, el)
    key = key or el.get("guid") or "unknown"
    sid = el.get("storey_id")
    view_id = el.get("_view_id")
    anchor = view.anchor(el) if view else el.get("anchor")
    if source == "drawing_model":
        anchor = el.get("anchor")
    dm_view = ModelView({"storeys": [], "elements": []})  # helper for geometry on pseudo elements
    dim_view = view or dm_view
    base_kw = dict(elements=[el["guid"]] if source == "building_model" else [], storey_id=sid, anchor=anchor,
                   source=source, view_id=view_id)

    def dims_for(v):
        try:
            return dims.element_dims(dim_view, el, measure, v, unit)
        except Exception:
            return []

    # --- exists
    if ctype == "exists":
        if value is None:
            f = env.review(key, "missing_measure", f"Check whether '{measure}' is present on this element.",
                           f"{subj_en}: '{measure}' could not be determined", f"{subj_tr}: '{measure}' belirlenemedi",
                           measured=M(None, unit, prov), **base_kw)
            return f
        ok = bool(value) and value != 0
        st = "pass" if ok else "violation"
        return env.finding(st, key, f"{subj_en}: {en_l} {'present' if ok else 'missing'}",
                           f"{subj_tr}: {tr_l} {'mevcut' if ok else 'eksik'}",
                           measured=M(num(value), unit, prov) if num(value) is not None else {"value": value, "unit": unit, "provenance": prov},
                           required={"op": "exists", "value": True, "unit": unit}, **base_kw)

    raw_limit = chk.get("limit")
    if ctype == "equals" and isinstance(raw_limit, (bool, str)) and not env.overridden():
        limit = 0.0  # placeholder, handled below
    if limit is None:
        if lnote:
            return env.review(key, "missing_context", f"Set the project context needed to choose the limit: {lnote}.",
                              f"{subj_en}: limit cannot be selected ({lnote})", f"{subj_tr}: sınır değeri seçilemedi ({lnote})",
                              measured=M(num(value), unit, prov), **base_kw)
        raise ValueError(f"rule {env.rule.get('id')} has no numeric limit")

    # --- equality against non-numeric reference (bool/str)
    if ctype == "equals" and (isinstance(raw_limit, (bool, str)) and not env.overridden()):
        if value is None:
            return env.review(key, "missing_measure", f"Check '{measure}' manually.", f"{subj_en}: {en_l} unknown",
                              f"{subj_tr}: {tr_l} bilinmiyor", **base_kw)
        ok = _eq(value, raw_limit)
        if not ok and prov == "inferred":
            return env.review(key, "low_confidence",
                              f"'{measure}' is inferred heuristically for this element and says the requirement is not met - verify on the plans.",
                              f"{subj_en}: {en_l} is {value}; required {raw_limit} (inferred value)",
                              f"{subj_tr}: {tr_l} {value}; olması gereken {raw_limit} (tahmin)",
                              measured={"value": value, "unit": unit, "provenance": prov},
                              required={"op": "==", "value": raw_limit, "unit": unit}, **base_kw)
        return env.finding("pass" if ok else "violation", key, f"{subj_en}: {en_l} is {value}; required {raw_limit}",
                           f"{subj_tr}: {tr_l} {value}; olması gereken {raw_limit}",
                           measured={"value": value, "unit": unit, "provenance": prov},
                           required={"op": "==", "value": raw_limit, "unit": unit}, **base_kw)

    tol = env.tol(default_tolerance(unit))
    v = judge(value, op, limit, limit_max=limit_max, tol=tol, prov=prov, min_prov=env.min_provenance,
              semi=env.semi, exceptions=env.exceptions, legal=env.legal, label=en_l)
    num_v = num(value)
    if v.status == "violation" and chk.get("target", {}).get("where"):
        w = chk["target"]["where"]
        keys = list(w.keys()) if isinstance(w, dict) else re.findall(r"[A-Za-z_][\w.]*", str(w))
        weak = [k for k in keys if (el.get("provenance") or {}).get(k) == "inferred"]
        if weak:
            from .judge import Verdict
            v = Verdict("review", "low_confidence",
                        f"The rule only targets elements where {', '.join(weak)} holds, but that property was inferred "
                        "heuristically for this element - confirm it on the plans.", False)
    en, tr = describe(subj_en, subj_tr, en_l, tr_l, num_v, unit, op, limit, limit_max)
    if lnote and lnote != "overridden":
        en += f" ({lnote})"
    if lnote == "overridden":
        en += " (project override)"
        tr += " (proje değeri)"
    if v.status == "violation" and source == "drawing_model":
        from .view import dm_room_doubt
        from .judge import Verdict
        doubt = dm_room_doubt(el)
        if doubt:
            v = Verdict("review", "low_confidence", f"Drawing-derived value, but {doubt}. Verify on the drawing.", False)
    return env.from_verdict(v, key, en, tr, measured=M(num_v, unit, prov),
                            required=R(op, limit, unit, limit_max),
                            dimensions=dims_for(num_v), **base_kw)


def base_unit_of(env: Env) -> str:
    from .util import base_unit
    return base_unit(env.unit) or "m"


def evaluate(env: Env) -> list[dict]:
    chk = env.check
    ctype = chk.get("type")
    if ctype not in ("min", "max", "range", "equals", "exists"):
        raise ValueError(f"unknown check.type {ctype!r}")
    tgt = chk.get("target") or {}
    kind = tgt.get("kind")
    if not kind:
        raise ValueError("declarative rule without target.kind")
    if not env.bm and not (env.dm and kind == "space"):
        return [env.na(f"Requires a building model with '{kind}' elements - none provided",
                       f"'{kind}' elemanları içeren bir yapı modeli gerekir - sağlanmadı", key="model")]
    elems, source = select_targets(env)

    # exists without measure -> model-level existence
    if ctype == "exists" and not chk.get("measure"):
        need = int(num(chk.get("limit")) or 1)
        n = len(elems)
        if n >= need:
            return [env.finding("pass", "model", f"{n} matching {kind} element(s) found (need {need})",
                                f"{n} adet uygun '{kind}' elemanı bulundu (gereken {need})",
                                elements=[e["guid"] for e in elems[:20]], source=source,
                                measured=M(n, "", None), required={"op": ">=", "value": need, "unit": ""})]
        if chk.get("absence_is_violation"):
            st, reason, hint = "violation", None, None
        else:
            st, reason, hint = "review", "missing_measure", (
                f"No matching {kind} element found in the model; confirm on the drawings whether it exists "
                "(it may simply not be modelled).")
        return [env.finding(st, "model", f"Required {kind} element not found in the model ({n} of {need})",
                            f"Gerekli '{kind}' elemanı modelde bulunamadı ({n}/{need})", reason=reason, hint=hint,
                            source=source, measured=M(n, "", None), required={"op": ">=", "value": need, "unit": ""})]

    if not elems:
        return [env.na(f"No '{kind}' element matches the rule target - nothing to check",
                       f"Kural hedefine uyan '{kind}' elemanı yok", key="model", source=source)]
    if kind == "railing" and env.bm:
        return _railings(env, elems, source)
    out = [evaluate_element(env, e, source) for e in elems]
    if source == "building_model" and env.dm and kind == "space":
        out += _dm_crosscheck(env, elems, out)
    return out


def _railings(env: Env, elems: list[dict], source: str) -> list[dict]:
    """Railing rules: stair handrails are not guards; a low railing beside a stair may be a handrail."""
    from .checks.openings import HANDRAIL_KW, _bbox_overlap
    from .util import has_kw
    bm = env.bm
    stairs = bm.of_kind("stair")
    out, hand = [], []
    for r in elems:
        if has_kw(f"{r.get('name')} {r.get('object_type')}", HANDRAIL_KW):
            hand.append(ModelView.name(r))
            continue
        f = evaluate_element(env, r, source)
        bb = r.get("bbox")
        if f["status"] == "violation" and bb and any(
                s.get("bbox") and _bbox_overlap(bb, s["bbox"], 0.5, True) for s in stairs):
            h = (f.get("measured") or {}).get("value")
            if h is not None and h >= 0.85:
                f["status"], f["review_reason"] = "review", "legal_judgement"
                f["review_hint"] = ("Railing beside a stair is below the guard height; it may be a handrail (kupeste, ~0.90 m) "
                                    "rather than a guard. Check whether the stair has a guard of the required height.")
        out.append(f)
    if hand:
        out.append(env.na(f"{len(hand)} handrail(s) skipped (not guards): " + ", ".join(hand[:10]),
                          f"{len(hand)} kupeste atlandi (korkuluk degil)", key="handrails"))
    return out


# ----------------------------------------------------------------------------- drawing cross-check
def _dm_crosscheck(env: Env, ifc_spaces: list[dict], ifc_findings: list[dict]) -> list[dict]:
    """Evaluate the same rule on drawing rooms; report only where drawing and IFC disagree."""
    dm, bm = env.dm, env.bm
    if not dm or not dm.rooms or not bm:
        return []
    tgt = env.check.get("target") or {}
    cands = []
    for r in dm.rooms:
        el = dm.room_as_space(r)
        u = el["measures"].get("usage")
        if tgt.get("usage_in") and u not in tgt["usage_in"]:
            continue
        if tgt.get("usage_not_in") and u in tgt["usage_not_in"]:
            continue
        cands.append(el)
    res: list[dict] = []
    used: set[str] = set()
    by_guid = {f["element_guids"][0]: f for f in ifc_findings if f.get("element_guids")}
    for el in cands:
        a = num(el["measures"].get("net_floor_area"))
        best, bd = None, 1e9
        for sp in ifc_spaces:
            if sp["guid"] in used:
                continue
            if sp["measures"].get("usage") != el["measures"].get("usage"):
                continue
            sa = num(measure_value(bm, sp, "net_floor_area")[0])
            if a is None or sa is None or sa <= 0:
                continue
            d = abs(a - sa) / sa
            if d < 0.15 and d < bd:
                best, bd = sp, d
        if best is None:
            continue
        used.add(best["guid"])
        f_ifc = by_guid.get(best["guid"])
        try:
            f_dm = evaluate_element(env, el, "drawing_model", key=el["guid"])
        except Exception:
            continue
        if not f_ifc or f_ifc["status"] in ("review", "not_applicable") or f_dm["status"] in ("review", "not_applicable"):
            continue
        if f_ifc["status"] != f_dm["status"]:
            f_dm["status"] = "review"
            f_dm["review_reason"] = "low_confidence"
            f_dm["review_hint"] = (f"The IFC model says '{f_ifc['status']}' but the drawing says "
                                   f"'{('violation' if f_ifc['status'] == 'pass' else 'pass')}' for the same room "
                                   f"({ModelView.name(best)}); the drawing is secondary - reconcile the two files.")
            f_dm["severity"] = env.rule.get("severity") or "warning"
            f_dm["message_en"] = "[drawing differs from IFC] " + f_dm["message_en"]
            f_dm["message_tr"] = "[çizim IFC'den farklı] " + f_dm["message_tr"]
            f_dm["highlight"] = [{"guid": best["guid"], "role": "context"}]
            f_dm["element_guids"] = []
            res.append(f_dm)
    return res
