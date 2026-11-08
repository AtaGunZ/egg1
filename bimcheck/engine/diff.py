"""diff_findings: compare two run_check results (or finding lists) for the live-recheck UI."""
from __future__ import annotations

from typing import Any

ACTIVE = ("violation", "review")


def _as_list(x: Any) -> list[dict]:
    if x is None:
        return []
    if isinstance(x, dict):
        return list(x.get("findings") or [])
    return list(x)


def _val(f: dict) -> Any:
    m = f.get("measured") or {}
    v = m.get("value")
    return round(v, 4) if isinstance(v, (int, float)) and not isinstance(v, bool) else v


def diff_findings(old: Any, new: Any) -> dict:
    """{"new": [...], "resolved": [...], "changed": [...]}

    new      : active (violation/review) findings that did not exist or were not active before
    resolved : findings that were active before and are gone or now pass / not_applicable
               (the *old* finding is returned, with `resolution` = "removed" | "now_pass" | "now_not_applicable")
    changed  : findings present in both whose status or measured value differ and that are not already
               listed as new/resolved (the *new* finding, plus `previous` = {status, value, message_en})"""
    o = {f["id"]: f for f in _as_list(old)}
    n = {f["id"]: f for f in _as_list(new)}
    out_new, out_res, out_chg = [], [], []
    for fid, f in n.items():
        p = o.get(fid)
        if f["status"] in ACTIVE and (p is None or p["status"] not in ACTIVE):
            out_new.append(f)
    for fid, p in o.items():
        if p["status"] not in ACTIVE:
            continue
        f = n.get(fid)
        if f is None:
            out_res.append({**p, "resolution": "removed"})
        elif f["status"] not in ACTIVE:
            out_res.append({**p, "resolution": "now_pass" if f["status"] == "pass" else "now_not_applicable",
                            "current": {"status": f["status"], "value": _val(f), "message_en": f.get("message_en")}})
    listed = {f["id"] for f in out_new} | {f["id"] for f in out_res}
    for fid, f in n.items():
        p = o.get(fid)
        if p is None or fid in listed:
            continue
        if p["status"] != f["status"] or _val(p) != _val(f) or p.get("review_reason") != f.get("review_reason"):
            out_chg.append({**f, "previous": {"status": p["status"], "value": _val(p), "message_en": p.get("message_en"),
                                              "review_reason": p.get("review_reason")}})
    return {"new": out_new, "resolved": out_res, "changed": out_chg}
