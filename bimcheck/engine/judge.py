"""Verdict logic: compare a measured value against a limit and decide pass / violation / review honestly."""
from __future__ import annotations

from dataclasses import dataclass

from .util import num, numbers_in_text

PROV_RANK = {"quantity": 3, "property": 2, "geometry": 1, "inferred": 0}

BAND_INFERRED = 0.05   # relative band around the limit where an `inferred` value cannot decide
BAND_BELOW_MIN = 0.08  # ... where provenance is weaker than the rule's `min_provenance`
BAND_SEMI = 0.05       # ... where a `semi` rule is "on the edge"


def prov_rank(p: str | None) -> int:
    return PROV_RANK.get(p or "", 1)


@dataclass
class Verdict:
    status: str                    # pass | violation | review
    reason: str | None = None      # review_reason
    hint: str | None = None        # review_hint
    ok: bool | None = None         # raw compliance (None when unknown)
    borderline: bool = False

    @property
    def is_review(self) -> bool:
        return self.status == "review"


def compare(value: float, op: str, limit: float, tol: float = 0.0, limit_max: float | None = None) -> bool:
    """Tolerance is granted in favour of the designer (rounded drawing values)."""
    if op == ">=":
        return value >= limit - tol
    if op == ">":
        return value > limit - tol
    if op == "<=":
        return value <= limit + tol
    if op == "<":
        return value < limit + tol
    if op in ("==", "="):
        return abs(value - limit) <= tol
    if op == "!=":
        return abs(value - limit) > tol
    if op == "range":
        hi = limit_max if limit_max is not None else limit
        return limit - tol <= value <= hi + tol
    raise ValueError(f"unsupported operator {op!r}")


def bound_distance(value: float, op: str, limit: float, limit_max: float | None = None) -> float:
    if op == "range":
        hi = limit_max if limit_max is not None else limit
        return min(abs(value - limit), abs(value - hi))
    return abs(value - limit)


def _bound_for_band(op: str, limit: float, limit_max: float | None, value: float) -> float:
    if op == "range" and limit_max is not None and abs(value - limit_max) < abs(value - limit):
        return limit_max
    return limit


def plausible_exception(exceptions: list[str] | None, value: float, op: str, limit: float, tol: float) -> str | None:
    """Return the exception text whose numeric alternative limit would be satisfied by `value`."""
    for text in exceptions or []:
        for alt in numbers_in_text(str(text)):
            if op in (">=", ">") and 0.8 * limit <= alt < limit and value >= alt - tol:
                return str(text)
            if op in ("<=", "<") and limit < alt <= 1.25 * limit and value <= alt + tol:
                return str(text)
    return None


def judge(value, op: str, limit: float, *, limit_max: float | None = None, tol: float = 0.0,
          prov: str | None = None, min_prov: str | None = None, semi: bool = False,
          exceptions: list[str] | None = None, legal: bool = False, label: str = "value") -> Verdict:
    v = num(value)
    if v is None:
        return Verdict("review", "missing_measure", f"The {label} could not be derived from the model - measure it manually.")
    ok = compare(v, op, limit, tol, limit_max)
    bound = _bound_for_band(op, limit, limit_max, v)
    dist = bound_distance(v, op, limit, limit_max)
    weak_inferred = prov == "inferred"
    weak_min = bool(min_prov) and prov_rank(prov) < prov_rank(min_prov)
    band = 0.0
    if weak_inferred:
        band = max(band, BAND_INFERRED)
    if weak_min:
        band = max(band, BAND_BELOW_MIN)
    if semi and prov_rank(prov) < prov_rank("property"):
        band = max(band, BAND_SEMI)  # semi rules: only values from geometry/inferred data are "on the edge"
    borderline = band > 0 and dist <= band * max(abs(bound), 1e-9)
    if borderline:
        if semi and not (weak_inferred or weak_min):  # geometry-derived value near the limit of a semi rule
            return Verdict("review", "low_confidence",
                           f"The {label} ({v:.3g}) is within {int(BAND_SEMI * 100)}% of the limit ({bound:.3g}); "
                           "this rule is only semi-automatic - confirm on the drawings.", ok, True)
        why = "inferred (heuristic)" if weak_inferred else f"taken from {prov or 'unknown'} data (rule asks for {min_prov})"
        return Verdict("review", "low_confidence",
                       f"The {label} ({v:.3g}) is close to the limit ({bound:.3g}) and its value is {why}; verify it.",
                       ok, True)
    if ok:
        return Verdict("pass", ok=True)
    ex = plausible_exception(exceptions, v, op, limit, tol)
    if ex:
        return Verdict("review", "exception_may_apply", f"Fails the general limit but an exception in the article may apply: {ex}", False)
    if legal:
        return Verdict("review", "legal_judgement", "Fails the numeric limit; whether the article applies here needs legal/administrative judgement.", False)
    return Verdict("violation", ok=False)


def judge_two(value, op: str, strict: float, loose: float, *, reason: str, hint: str, **kw):
    """Ambiguous classification (e.g. dwelling-entrance 1.00 vs other door 0.90).

    pass if the strict limit is met; violation if even the loose limit fails; otherwise review(reason).
    Returns (Verdict, 'strict'|'loose')."""
    vs = judge(value, op, strict, **kw)
    if vs.status == "pass":
        return vs, "strict"
    vl = judge(value, op, loose, **kw)
    if vl.status in ("violation", "review"):
        return vl, "loose"
    return Verdict("review", reason, hint, False), "strict"


WORST = {"violation": 3, "review": 2, "pass": 1, "not_applicable": 0}


def worst(*statuses: str) -> str:
    return max(statuses, key=lambda s: WORST.get(s, 0))
