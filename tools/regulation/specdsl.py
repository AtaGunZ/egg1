"""Tiny DSL used by rules_spec.py to declare rules compactly.

Every rule is declared with R(article, paragraph, item, ...); build_rules.py fills in text_tr / page / revision
from regulation/articles.json so the Turkish text is *always* the extracted current-in-force text.
"""
from __future__ import annotations

M, M2, M3 = "m", "m²", "m³"
ANY = None


def _target(kind, usage_in=None, usage_not_in=None, where=None):
    return {"kind": kind, "usage_in": usage_in, "usage_not_in": usage_not_in, "where": where}


def _check(type_, kind, measure=None, op=None, limit=None, limit_max=None, unit=None, tol=None, exceptions=None,
           custom_id=None, usage_in=None, usage_not_in=None, where=None, extra=None, limit_by=None):
    c = {"type": type_, "target": _target(kind, usage_in, usage_not_in, where), "measure": measure, "op": op,
         "limit": limit, "limit_max": limit_max, "unit": unit, "tolerance": tol, "limit_by": limit_by,
         "exceptions": exceptions or [], "custom_id": custom_id}
    if extra:
        c["extra"] = extra
    return c


def mn(kind, measure, limit, unit=M, tol=0.005, **kw):
    return _check("min", kind, measure, ">=", limit, None, unit, tol, **kw)


def mx(kind, measure, limit, unit=M, tol=0.005, **kw):
    return _check("max", kind, measure, "<=", limit, None, unit, tol, **kw)


def rng(kind, measure, lo, hi, unit=M, tol=0.005, **kw):
    return _check("range", kind, measure, "range", lo, hi, unit, tol, **kw)


def eq(kind, measure, value, unit=None, **kw):
    return _check("equals", kind, measure, "==", value, None, unit, None, **kw)


def cu(custom_id, kind, limit=None, unit=None, limit_max=None, tol=0.005, op=None, **kw):
    """custom check: implemented by bimcheck.engine under `custom_id`; parameters live in check.extra"""
    return _check("custom", kind, None, op, limit, limit_max, unit, tol, custom_id=custom_id, **kw)


def man(kind="building", limit=None, unit=None, op=None, limit_max=None, **kw):
    """manual rule: informational check object only (limit documented for the human reviewer, never evaluated)"""
    return _check("custom", kind, None, op, limit, limit_max, unit, None, custom_id=None, **kw)


def aw(use=None, min_storeys=None, max_storeys=None, storey_kind=None, **extra):
    d = {"building_use": use, "min_storeys": min_storeys, "max_storeys": max_storeys, "storey_kind": storey_kind}
    if extra:
        d["extra"] = extra
    return d


def R(article, paragraph, item, *, tr, en, cat, auto, check, sev="error", req=("building_model",), when=None,
      notes="", needs="", deleg=None, rev=None, alt=None, unit=None):
    """paragraph is a string ('4'); item None | 'a' | 'a.1' | synthetic key (falls back to the paragraph text)."""
    return {
        "article": article, "paragraph": str(paragraph), "item": item, "title_tr": tr, "title_en": en,
        "category": cat, "automation": auto, "requires": list(req), "severity": sev,
        "applies_when": when or aw(), "check": check, "unit_display": unit or check["unit"] or "",
        "notes": notes, "needs": needs, "delegates_to": deleg or [], "rev_note": rev, "alt_requires": alt or [],
    }
