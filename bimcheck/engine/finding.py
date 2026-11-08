"""Finding construction: Env (everything a check needs) and message helpers."""
from __future__ import annotations

from typing import Any, Sequence

from .judge import Verdict
from .util import base_unit, fmt, num, to_base
from .view import DrawingView, ModelView

SCHEMA_VERSION = "1"


class Env:
    """Evaluation environment handed to every check function."""

    def __init__(self, rule: dict, bm: ModelView | None, dm: DrawingView | None, ctx: dict,
                 use: str | None = None, use_inferred: bool = False):
        self.rule = rule
        self.check = rule.get("check") or {}
        self.params: dict = {**(self.check.get("extra") or {}), **(self.check.get("params") or {})}
        self.rule_extra: dict = (rule.get("applies_when") or {}).get("extra") or {}
        self.automation = rule.get("automation") or "auto"
        self.bm = bm
        self.dm = dm
        self.ctx = ctx
        self.use = use
        self.use_inferred = use_inferred
        ov = (ctx.get("overrides") or {}).get(rule.get("id")) or {}
        self.override: dict = ov if isinstance(ov, dict) else {}
        self.unit = self.check.get("unit") or rule.get("unit_display") or "m"
        self.semi = self.automation == "semi"

    # ---- limits -----------------------------------------------------------------------------
    def limit(self, key: str = "limit", default: float | None = None, unit: str | None = None) -> float | None:
        """Limit in model base units: per-rule override > catalogue value > default (already base)."""
        u = unit or self.unit
        if key in self.override and self.override[key] is not None:
            return to_base(self.override[key], u)
        v = self.check.get(key)
        if v is not None and num(v) is not None:
            return to_base(v, u)
        return default

    def overridden(self, key: str = "limit") -> bool:
        return self.override.get(key) is not None

    @property
    def tolerance(self) -> float | None:
        t = num(self.override.get("tolerance"))
        if t is None:
            t = num(self.check.get("tolerance"))
        return None if t is None else to_base(t, self.unit)

    def tol(self, default: float) -> float:
        t = self.tolerance
        return default if t is None else t

    @property
    def exceptions(self) -> list[str]:
        off = self.ctx.get("exceptions_off") or []
        if self.rule.get("id") in off or self.ctx.get("hava_maniasi") is False and self.rule.get("id") == "KBB-28-4":
            return []
        ex = self.check.get("exceptions") or []
        return [str(x) for x in ex]

    @property
    def min_provenance(self) -> str | None:
        return self.check.get("min_provenance") or self.params.get("min_provenance")

    @property
    def legal(self) -> bool:
        return bool(self.check.get("legal_judgement") or self.params.get("legal_judgement"))

    # ---- finding ----------------------------------------------------------------------------
    def finding(self, status: str, key: str, message_en: str, message_tr: str, *,
                elements: Sequence[str] = (), context_elements: Sequence[str] = (),
                storey_id: str | None = None, measured: dict | None = None, required: dict | None = None,
                reason: str | None = None, hint: str | None = None, anchor: Sequence[float] | None = None,
                dimensions: list[dict] | None = None, source: str | None = None, view_id: str | None = None,
                extra: dict | None = None) -> dict:
        r = self.rule
        offending = status in ("violation", "review")
        guids = [g for g in elements if g]
        hl = [{"guid": g, "role": "offending" if offending else "context"} for g in guids]
        for g in context_elements:
            if g and g not in guids:
                hl.append({"guid": g, "role": "context"})
        if source is None:
            source = "building_model" if self.bm else "drawing_model"
        f = {
            "id": f"{r.get('id')}:{key}",
            "rule_id": r.get("id"), "article": r.get("article"), "paragraph": r.get("paragraph"),
            "title_tr": r.get("title_tr"), "title_en": r.get("title_en"), "category": r.get("category"),
            "status": status,
            "severity": (r.get("severity") or "error") if offending else "info",
            "message_en": message_en, "message_tr": message_tr,
            "measured": measured, "required": required,
            "review_reason": reason if status == "review" else None,
            "review_hint": hint if status == "review" else None,
            "element_guids": guids,
            "storey_id": storey_id,
            "storey_name": self.bm.storey_name(storey_id) if (self.bm and storey_id) else None,
            "highlight": hl,
            "anchor": [round(float(c), 4) for c in anchor] if anchor else None,
            "dimensions": dimensions or [],
            "regulation_excerpt": r.get("text_tr"),
            "source": source,
            "view_id": view_id,
        }
        if self.use_inferred and self.rule.get("applies_when", {}) and (self.rule["applies_when"] or {}).get("building_use"):
            f.setdefault("extra", {})["building_use_inferred"] = self.use
        if extra:
            f.setdefault("extra", {}).update(extra)
        return f

    def from_verdict(self, v: Verdict, key: str, message_en: str, message_tr: str, **kw) -> dict:
        return self.finding(v.status, key, message_en, message_tr, reason=v.reason, hint=v.hint, **kw)

    def na(self, reason_en: str, reason_tr: str | None = None, key: str = "model", **kw) -> dict:
        return self.finding("not_applicable", key, reason_en, reason_tr or reason_en, **kw)

    def review(self, key: str, reason: str, hint: str, message_en: str, message_tr: str, **kw) -> dict:
        return self.finding("review", key, message_en, message_tr, reason=reason, hint=hint, **kw)


# ------------------------------------------------------------------------------ message helpers
def M(value: float | None, unit: str = "m", prov: str | None = None) -> dict:
    return {"value": None if value is None else round(float(value), 4), "unit": unit, "provenance": prov}


def R(op: str, value: float | None, unit: str = "m", value_max: float | None = None) -> dict:
    d = {"op": op, "value": None if value is None else round(float(value), 4), "unit": unit}
    if value_max is not None:
        d["value_max"] = round(float(value_max), 4)
    return d


_OP_EN = {">=": "minimum", ">": "must exceed", "<=": "maximum", "<": "must be below", "==": "required", "=": "required",
          "!=": "must differ from", "range": "required range"}
_OP_TR = {">=": "en az", ">": "değerinden büyük olmalı", "<=": "en fazla", "<": "değerinden küçük olmalı",
          "==": "olması gereken", "=": "olması gereken", "!=": "farklı olmalı", "range": "izin verilen aralık"}


def describe(subject_en: str, subject_tr: str, label_en: str, label_tr: str, value: float | None, unit: str,
             op: str, limit: float | None, limit_max: float | None = None, nd: int | None = None) -> tuple[str, str]:
    """('Bedroom X: clear height is 2.45 m; minimum is 2.60 m', TR)"""
    if value is None:
        return (f"{subject_en}: {label_en} could not be determined from the model",
                f"{subject_tr}: {label_tr} modelden belirlenemedi")
    lim_s = fmt(limit, unit, nd)
    if op == "range" and limit_max is not None:
        lim_s = f"{fmt(limit, unit, nd)} - {fmt(limit_max, unit, nd)}"
    en = f"{subject_en}: {label_en} is {fmt(value, unit, nd)}; {_OP_EN.get(op, op)} {lim_s}"
    if op in (">", "<", "!="):
        en = f"{subject_en}: {label_en} is {fmt(value, unit, nd)}; {_OP_EN.get(op, op)} {lim_s}"
    tr = f"{subject_tr}: {label_tr} {fmt(value, unit, nd)}; {_OP_TR.get(op, op)} {lim_s}"
    if op in (">", "<"):
        tr = f"{subject_tr}: {label_tr} {fmt(value, unit, nd)}; {lim_s} {_OP_TR[op]}"
    return en, tr


def subject(view: ModelView | None, el: dict, kind_en: str, kind_tr: str) -> tuple[str, str]:
    nm = ModelView.name(el)
    return f"{kind_en} '{nm}'", f"{kind_tr} '{nm}'"


MEASURE_LABEL = {  # measure -> (EN, TR, unit)
    "height": ("clear height", "iç yükseklik", "m"),
    "net_floor_area": ("net floor area", "net alan", "m²"),
    "gross_floor_area": ("gross floor area", "brüt alan", "m²"),
    "area": ("area", "alan", "m²"),
    "min_width": ("minimum width", "dar kenar", "m"),
    "max_length": ("maximum length", "en büyük uzunluk", "m"),
    "perimeter": ("perimeter", "çevre", "m"),
    "width": ("width", "genişlik", "m"),
    "sill_height": ("sill height", "denizlik yüksekliği", "m"),
    "riser_height": ("riser height", "basamak yüksekliği", "m"),
    "tread_depth": ("tread depth", "basamak genişliği", "m"),
    "thickness": ("thickness", "kalınlık", "m"),
    "length": ("length", "uzunluk", "m"),
    "total_rise": ("total rise", "toplam yükseklik", "m"),
    "clear_headroom": ("clear headroom", "baş yüksekliği", "m"),
}


def label_for(measure: str) -> tuple[str, str, str]:
    return MEASURE_LABEL.get(measure, (measure.replace("_", " "), measure.replace("_", " "), "m"))


def unit_for(measure: str, rule_unit: str | None) -> str:
    """Display unit in base terms: area-like measures get m², else from rule unit."""
    if measure in ("net_floor_area", "gross_floor_area", "area", "window_area"):
        return "m²"
    return base_unit(rule_unit) or label_for(measure)[2]
