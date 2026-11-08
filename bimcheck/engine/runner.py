"""run_check: orchestrates rules x models x context -> findings (CONTRACTS section 5)."""
from __future__ import annotations

import json
import traceback
from pathlib import Path
from typing import Any

from . import checks, declarative
from .finding import SCHEMA_VERSION, Env
from .view import DrawingView, ModelView, effective_use

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_RULES = REPO_ROOT / "rules" / "kayseri.rules.json"
FALLBACK_RULES = REPO_ROOT / "tests" / "engine" / "fixtures" / "mini_rules.json"

_rules_cache: dict[str, tuple[float, dict]] = {}


def load_rules(rules: dict | str | Path | None = None) -> tuple[dict | None, str | None]:
    """(catalogue, error). `rules` may be a dict, a path, or None (default catalogue, mini fallback)."""
    if isinstance(rules, dict):
        return rules, None
    path: Path | None = Path(rules) if rules else None
    if path is None:
        path = DEFAULT_RULES if DEFAULT_RULES.exists() else (FALLBACK_RULES if FALLBACK_RULES.exists() else None)
    if path is None or not path.exists():
        return None, f"no rule catalogue found ({DEFAULT_RULES} does not exist yet)"
    key = str(path)
    mt = path.stat().st_mtime
    hit = _rules_cache.get(key)
    if hit and hit[0] == mt:
        return hit[1], None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception as e:  # noqa: BLE001
        return None, f"cannot read rule catalogue {path}: {e}"
    _rules_cache[key] = (mt, data)
    return data, None


def _applicable(rule: dict, bm: ModelView | None, dm: DrawingView | None, ctx: dict, use: str | None,
                use_inferred: bool) -> tuple[bool, str | None, str | None]:
    """(applies, reason_en, reason_tr). Applicability beyond this is decided by the check itself."""
    aw = rule.get("applies_when") or {}
    bu = aw.get("building_use")
    if bu:
        bu = [bu] if isinstance(bu, str) else list(bu)
        if use is not None and use not in bu and not (use == "mixed" and ({"residential", "commercial"} & set(bu))):
            return (False, f"Rule applies to {', '.join(bu)} buildings; this project's use is '{use}'"
                    + (" (inferred from space names)" if use_inferred else ""),
                    f"Kural {', '.join(bu)} binaları için geçerli; proje kullanımı '{use}'")
    ex = aw.get("extra") or {}
    zones = ex.get("zone_type")
    if zones:
        zones = [zones] if isinstance(zones, str) else list(zones)
        zone = ctx.get("zone_type") or {"residential": "konut", "commercial": "ticaret", "mixed": "karma"}.get(use or "")
        if zone is not None and zone not in zones:
            return False, f"Rule applies to zone type {', '.join(zones)}; project zone is '{zone}'", f"Kural {', '.join(zones)} bölgeleri için geçerli"
    if ex.get("ground_floor_commerce") and not ctx.get("ground_floor_commerce"):
        g = bm.ground_storey if bm else None
        if not (g and any((bm.measure(s, "usage") == "commercial") for s in bm.storey_spaces(g["id"]))):
            return False, "Rule applies to ground floors with shops; none found", "Kural zemin kat ticaret kullanımı için geçerli"
    n = None
    plan_first = (rule.get("check") or {}).get("custom_id") == "parcel_dimensions"
    if plan_first and ctx.get("max_storeys") is not None:
        try:
            n = int(ctx["max_storeys"])
        except (TypeError, ValueError):
            n = None
    if n is None and bm:
        n = bm.storey_counts()["total"] or None
    if n is None and ctx.get("max_storeys") is not None:
        try:
            n = int(ctx["max_storeys"])
        except (TypeError, ValueError):
            n = None
    mn, mx = aw.get("min_storeys"), aw.get("max_storeys")
    if n is not None:
        if mn is not None and n < mn:
            return False, f"Rule applies from {mn} storeys; the building has {n}", f"Kural {mn} kat ve üzeri için geçerli; bina {n} katlı"
        if mx is not None and n > mx:
            return False, f"Rule applies up to {mx} storeys; the building has {n}", f"Kural en çok {mx} kat için geçerli; bina {n} katlı"
    return True, None, None


def _complete(f: dict) -> dict:
    """Make sure every contract field exists."""
    defaults = {"rule_id": None, "article": None, "paragraph": None, "title_tr": None, "title_en": None, "category": None,
                "status": "review", "severity": "info", "message_en": "", "message_tr": "", "measured": None, "required": None,
                "review_reason": None, "review_hint": None, "element_guids": [], "storey_id": None, "storey_name": None,
                "highlight": [], "anchor": None, "dimensions": [], "regulation_excerpt": None,
                "source": "building_model", "view_id": None}
    for k, v in defaults.items():
        f.setdefault(k, v)
    return f


def run_check(building_model: dict | None, drawing_model: dict | None, context: dict | None,
              rules: dict | None = None, *, rule_ids: list[str] | None = None) -> dict:
    ctx = dict(context or {})
    bm = ModelView(building_model) if building_model else None
    dm = DrawingView(drawing_model) if drawing_model else None
    catalogue, load_err = load_rules(rules)
    errors: list[str] = []
    if load_err:
        errors.append(load_err)
    rule_list = list((catalogue or {}).get("rules") or [])
    if rule_ids is not None:
        wanted = set(rule_ids)
        rule_list = [r for r in rule_list if r.get("id") in wanted]
    use, use_inferred = effective_use(ctx, bm, dm)
    findings: list[dict] = []
    evaluated = skipped_manual = n_a_rules = crashed = 0

    for rule in rule_list:
        rid = rule.get("id")
        try:
            if (rule.get("automation") or "auto") == "manual":
                skipped_manual += 1
                continue
            env = Env(rule, bm, dm, ctx, use, use_inferred)
            if env.override.get("disabled"):
                fs = [env.na("Rule disabled by project override", "Kural proje ayarıyla devre dışı bırakıldı", key="model",
                             source="building_model" if bm else "drawing_model")]
            else:
                ok, why_en, why_tr = _applicable(rule, bm, dm, ctx, use, use_inferred)
                if not ok:
                    fs = [env.na(why_en, why_tr, key="model", source="building_model" if bm else "drawing_model")]
                else:
                    fs = _evaluate_rule(env)
            fs = [_complete(f) for f in fs]
            findings.extend(fs)
            if any(f["status"] != "not_applicable" for f in fs):
                evaluated += 1
            else:
                n_a_rules += 1
        except Exception as e:  # noqa: BLE001 - one rule must never abort the run
            crashed += 1
            tb = traceback.extract_tb(e.__traceback__)
            where = f" at {Path(tb[-1].filename).name}:{tb[-1].lineno}" if tb else ""
            errors.append(f"rule {rid} crashed: {type(e).__name__}: {e}{where}")

    _unique_ids(findings)
    counts = {"violation": 0, "review": 0, "pass": 0, "not_applicable": 0}
    for f in findings:
        counts[f["status"]] = counts.get(f["status"], 0) + 1
    summary = {**counts, "rules_evaluated": evaluated, "rules_skipped_manual": skipped_manual,
               "rules_not_applicable": n_a_rules, "rules_crashed": crashed, "errors": errors}
    if use is not None:
        summary["building_use"] = {"value": use, "inferred": use_inferred}
    return {"schema_version": SCHEMA_VERSION, "summary": summary, "findings": findings}


def _evaluate_rule(env: Env) -> list[dict]:
    chk = env.check
    ctype = chk.get("type")
    if ctype == "custom" or (chk.get("custom_id") and ctype not in ("min", "max", "range", "equals", "exists")):
        cid = chk.get("custom_id")
        fn = checks.get(cid)
        if fn is None:
            return [env.review("model", "legal_judgement",
                               f"The check '{cid}' is not implemented in this engine version - evaluate this article manually.",
                               f"Check '{cid}' is not implemented - needs manual review",
                               f"'{cid}' kontrolü henüz uygulanmadı - elle incelenmeli",
                               source="building_model" if env.bm else "drawing_model")]
        return fn(env) or []
    return declarative.evaluate(env)


def _unique_ids(findings: list[dict]) -> None:
    seen: dict[str, int] = {}
    for f in findings:
        base = f["id"]
        n = seen.get(base, 0)
        seen[base] = n + 1
        if n:
            f["id"] = f"{base}#{n + 1}"
