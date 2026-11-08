"""Helpers shared by the custom checks."""
from __future__ import annotations

from dataclasses import dataclass, field

from ..finding import Env
from ..judge import WORST, Verdict
from ..util import bbox_center, num
from ..view import ModelView


def need_building_model(env: Env, what: str = "elements") -> list[dict] | None:
    if env.bm is None:
        return [env.na(f"Requires a building model ({what}) - none provided",
                       f"Yapı modeli gerekir ({what}) - sağlanmadı")]
    return None


def model_bounds(bm: ModelView) -> tuple[list[float], list[float]] | None:
    mn = [1e18, 1e18, 1e18]
    mx = [-1e18, -1e18, -1e18]
    found = False
    for e in bm.elements:
        bb = e.get("bbox")
        if not bb:
            continue
        found = True
        for i in range(3):
            mn[i] = min(mn[i], bb["min"][i])
            mx[i] = max(mx[i], bb["max"][i])
    return (mn, mx) if found else None


def model_center(bm: ModelView) -> list[float] | None:
    b = model_bounds(bm)
    if not b:
        return None
    return [(b[0][i] + b[1][i]) / 2 for i in range(3)]


def storey_anchor(bm: ModelView, st: dict) -> list[float] | None:
    """Representative (x, y, floor) of a storey: mean of its space anchors, else model centre."""
    sid = st.get("id")
    pts = [bm.anchor(e) for e in bm.of_kind("space") if e.get("storey_id") == sid]
    pts = [p for p in pts if p]
    z = num(st.get("elevation")) or 0.0
    if pts:
        return [sum(p[0] for p in pts) / len(pts), sum(p[1] for p in pts) / len(pts), z]
    c = model_center(bm)
    return [c[0], c[1], z] if c else None


def get_spaces(env: Env) -> tuple[list[dict], str]:
    """IFC spaces when present, otherwise drawing rooms dressed as spaces."""
    if env.bm and env.bm.of_kind("space"):
        return env.bm.of_kind("space"), "building_model"
    if env.dm and env.dm.rooms:
        return [env.dm.room_as_space(r) for r in env.dm.rooms], "drawing_model"
    return [], "building_model"


@dataclass
class Part:
    """One sub-test of a multi-part check (e.g. min side + min area of a room)."""
    key: str
    label_en: str
    label_tr: str
    value: float | None
    prov: str | None
    op: str
    limit: float | None
    unit: str
    verdict: Verdict
    limit_max: float | None = None
    note: str = ""
    extra: dict = field(default_factory=dict)


def merge_parts(parts: list[Part]) -> tuple[str, str | None, str | None, Part]:
    """Worst status over parts; primary part = first part with the worst status."""
    best = max(parts, key=lambda p: WORST[p.verdict.status])
    st = best.verdict.status
    hints = [p.verdict.hint for p in parts if p.verdict.status == "review" and p.verdict.hint]
    reason = best.verdict.reason if st == "review" else None
    return st, reason, (" ".join(dict.fromkeys(hints)) or None) if st == "review" else None, best


def parts_extra(parts: list[Part]) -> list[dict]:
    return [{"measure": p.key, "value": None if p.value is None else round(p.value, 4), "unit": p.unit,
             "op": p.op, "limit": None if p.limit is None else round(p.limit, 4), "status": p.verdict.status}
            for p in parts]
