"""Rule catalogue access + validation (CONTRACTS.md section 4).

    from bimcheck.regulation.catalogue import load_rules, load_articles, get_rule, validate_catalogue
    cat = load_rules()                       # dict, rules/kayseri.rules.json
    rule = get_rule("KBB-28-4")              # dict | None
    problems = validate_catalogue(cat)       # [] when valid

Authoring helpers (see rules/AUTHORING.md): `merge_catalogues`, `apply_overrides`.
"""
from __future__ import annotations

import copy
import json
import re
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_RULES = ROOT / "rules" / "kayseri.rules.json"
DEFAULT_ARTICLES = ROOT / "regulation" / "articles.json"

# ----------------------------------------------------------------------------- vocabularies (CONTRACTS.md)
ALLOWED_CUSTOM_IDS = frozenset({
    "stair_riser_vs_elevator", "stair_tread_formula", "stair_width", "elevator_required", "storey_height_max",
    "room_min_dims_area", "living_room_exterior_light", "door_dimensions", "window_sill_guard",
    "entrance_corridor_width", "parcel_setbacks", "taks_kaks", "max_storeys", "parcel_dimensions",
    "light_well_size", "garden_wall_height",
})

# Measure names per element kind, exactly as in CONTRACTS.md section 1 (BuildingModel), plus the storey fields.
MEASURES_BY_KIND: dict[str, frozenset] = {
    "space": frozenset({"net_floor_area", "gross_floor_area", "perimeter", "height", "floor_z", "ceiling_z",
                        "min_width", "max_length", "has_exterior_window", "window_area"}),
    "door": frozenset({"width", "height", "is_external", "is_entrance", "thickness"}),
    "window": frozenset({"width", "height", "sill_height", "area", "is_external"}),
    "stair": frozenset({"riser_height", "tread_depth", "width", "step_count", "flight_count", "total_rise",
                        "clear_headroom"}),
    "railing": frozenset({"height", "length"}),
    "wall": frozenset({"thickness", "length", "height", "is_external"}),
    "slab": frozenset({"thickness", "area", "is_roof", "is_floor"}),
    "roof": frozenset({"area", "max_height_z"}),
    "covering": frozenset({"area"}),
    "column": frozenset(), "beam": frozenset(), "other": frozenset(),
    # pseudo kinds used by model/parcel-level (custom) rules; no declarative measures except storey fields
    "storey": frozenset({"height", "elevation"}),
    "building": frozenset(), "parcel": frozenset(),
}
ELEMENT_KINDS = frozenset(MEASURES_BY_KIND)
USAGES = frozenset({"living_room", "bedroom", "kitchen", "bathroom", "wc", "corridor", "hall", "stair", "storage",
                    "balcony", "terrace", "technical", "garage", "commercial", "other"})
CATEGORIES = frozenset({"heights", "rooms", "circulation", "stairs", "openings", "safety", "setbacks", "zoning",
                        "services", "accessibility", "other"})
AUTOMATION = frozenset({"auto", "semi", "manual"})
REQUIRES = frozenset({"building_model", "drawing_model", "parcel_context"})
SEVERITIES = frozenset({"error", "warning", "info"})
CHECK_TYPES = frozenset({"min", "max", "range", "equals", "exists", "custom"})
REVISION_STATUS = frozenset({"current", "amended", "new"})
OPS = {"min": ">=", "max": "<=", "equals": "=="}

REQUIRED_RULE_KEYS = ("id", "article", "paragraph", "item", "title_tr", "title_en", "text_tr", "page", "category",
                      "automation", "requires", "severity", "applies_when", "check", "unit_display", "revision",
                      "notes")
REQUIRED_CHECK_KEYS = ("type", "target", "measure", "op", "limit", "limit_max", "unit", "tolerance", "limit_by",
                       "exceptions", "custom_id")
REQUIRED_TARGET_KEYS = ("kind", "usage_in", "usage_not_in", "where")
REQUIRED_APPLIES_KEYS = ("building_use", "min_storeys", "max_storeys", "storey_kind")

_TR_ASCII = {"ç": "cc", "ğ": "gg", "ı": "ii", "ö": "oo", "ş": "ss", "ü": "uu"}


def item_slug(item: str | None) -> str | None:
    """ASCII form of an item key as used inside rule ids: 'ç' -> 'cc', 'a.1' -> 'a-1'."""
    if item is None:
        return None
    out = "".join(_TR_ASCII.get(ch, ch) for ch in str(item).lower())
    return out.replace(".", "-")


def make_rule_id(article: int, paragraph: str, item: str | None = None, prefix: str = "KBB") -> str:
    rid = f"{prefix}-{article}-{paragraph}"
    if item:
        rid += "-" + item_slug(item)
    return rid


# ----------------------------------------------------------------------------- loading
_cache: dict[tuple, Any] = {}


def _load_json(path: Path):
    key = (str(path), path.stat().st_mtime_ns)
    if key not in _cache:
        _cache.clear()
        _cache[key] = json.loads(path.read_text(encoding="utf-8"))
    return _cache[key]


def load_rules(path: str | Path | None = None) -> dict:
    """Load the rule catalogue (default rules/kayseri.rules.json). Returns a deep copy (safe to mutate)."""
    p = Path(path) if path else DEFAULT_RULES
    return copy.deepcopy(_load_json(p))


def load_articles(path: str | Path | None = None) -> list:
    """Load regulation/articles.json (current-in-force article text with revisions)."""
    p = Path(path) if path else DEFAULT_ARTICLES
    return copy.deepcopy(_load_json(p))


def get_rule(rule_id: str, path: str | Path | None = None, catalogue: dict | None = None) -> dict | None:
    cat = catalogue if catalogue is not None else load_rules(path)
    for r in cat.get("rules", []):
        if r["id"] == rule_id:
            return r
    return None


def get_article(number: int, path: str | Path | None = None) -> dict | None:
    for a in load_articles(path):
        if a["article"] == number:
            return a
    return None


def rules_by_automation(cat: dict) -> dict[str, list[str]]:
    out: dict[str, list[str]] = {"auto": [], "semi": [], "manual": []}
    for r in cat["rules"]:
        out[r["automation"]].append(r["id"])
    return out


# ----------------------------------------------------------------------------- authoring helpers
def apply_overrides(cat: dict, overrides: dict[str, dict]) -> dict:
    """Return a copy of `cat` with per-rule overrides applied (ProjectContext.overrides semantics).

    Supported override keys: limit, limit_max, tolerance, severity, automation, enabled (False drops the rule),
    and any top-level rule key (e.g. 'notes')."""
    out = copy.deepcopy(cat)
    keep = []
    for r in out["rules"]:
        ov = overrides.get(r["id"])
        if ov:
            if ov.get("enabled") is False:
                continue
            for k, v in ov.items():
                if k in ("limit", "limit_max", "tolerance", "unit", "exceptions"):
                    r["check"][k] = v
                elif k != "enabled":
                    r[k] = v
            r["notes"] = (r.get("notes") or "") + " [overridden: " + ", ".join(sorted(ov)) + "]"
        keep.append(r)
    out["rules"] = keep
    return out


def merge_catalogues(base: dict, extra: dict) -> dict:
    """Merge another municipality's catalogue into `base`; rules with the same id in `extra` replace the base ones."""
    out = copy.deepcopy(base)
    index = {r["id"]: i for i, r in enumerate(out["rules"])}
    for r in extra.get("rules", []):
        if r["id"] in index:
            out["rules"][index[r["id"]]] = copy.deepcopy(r)
        else:
            out["rules"].append(copy.deepcopy(r))
    return out


# ----------------------------------------------------------------------------- validation
def _is_num(x) -> bool:
    return isinstance(x, (int, float)) and not isinstance(x, bool)


def validate_rule(r: dict, prefix: str = "KBB") -> list[str]:
    errs: list[str] = []
    rid = r.get("id", "<no id>")

    def err(msg):
        errs.append(f"{rid}: {msg}")

    for k in REQUIRED_RULE_KEYS:
        if k not in r:
            err(f"missing key '{k}'")
    if errs:
        return errs
    # id <-> article/paragraph/item
    if not isinstance(r["article"], int):
        err("article must be int")
    elif r["id"] != make_rule_id(r["article"], str(r["paragraph"]), r["item"], prefix):
        err(f"id does not match article/paragraph/item (expected {make_rule_id(r['article'], str(r['paragraph']), r['item'], prefix)})")
    if not re.fullmatch(rf"{prefix}-\d+-\d+(-[a-z0-9]+)*", r["id"]):
        err("id format must be KBB-<article>-<paragraph>[-<item>]")
    for k in ("title_tr", "title_en", "text_tr"):
        if not isinstance(r[k], str) or not r[k].strip():
            err(f"'{k}' must be a non-empty string")
    if r["page"] is not None and not isinstance(r["page"], int):
        err("page must be int|null")
    if r["category"] not in CATEGORIES:
        err(f"bad category {r['category']!r}")
    if r["automation"] not in AUTOMATION:
        err(f"bad automation {r['automation']!r}")
    if not isinstance(r["requires"], list) or not r["requires"] or not set(r["requires"]) <= REQUIRES:
        err(f"bad requires {r['requires']!r}")
    if r["severity"] not in SEVERITIES:
        err(f"bad severity {r['severity']!r}")
    aw = r["applies_when"]
    if not isinstance(aw, dict) or any(k not in aw for k in REQUIRED_APPLIES_KEYS):
        err("applies_when must contain building_use,min_storeys,max_storeys,storey_kind")
    else:
        bu = aw["building_use"]
        if bu is not None and not (isinstance(bu, list) and set(bu) <= {"residential", "commercial", "mixed", "other"}):
            err(f"bad applies_when.building_use {bu!r}")
    rev = r["revision"]
    if rev is not None and (not isinstance(rev, dict) or rev.get("status") not in REVISION_STATUS):
        err(f"bad revision {rev!r}")
    chk = r["check"]
    if not isinstance(chk, dict):
        err("check must be an object")
        return errs
    for k in REQUIRED_CHECK_KEYS:
        if k not in chk:
            err(f"check missing key '{k}'")
    if any(k not in chk for k in REQUIRED_CHECK_KEYS):
        return errs
    if chk["type"] not in CHECK_TYPES:
        err(f"bad check.type {chk['type']!r}")
        return errs
    tgt = chk["target"]
    if not isinstance(tgt, dict) or any(k not in tgt for k in REQUIRED_TARGET_KEYS):
        err("check.target must contain kind,usage_in,usage_not_in,where")
        return errs
    kind = tgt["kind"]
    if kind not in ELEMENT_KINDS:
        err(f"unknown target.kind {kind!r}")
    for k in ("usage_in", "usage_not_in"):
        u = tgt[k]
        if u is not None and not (isinstance(u, list) and set(u) <= USAGES):
            err(f"bad target.{k} {u!r}")
    if not isinstance(chk["exceptions"], list):
        err("check.exceptions must be a list")
    if chk["custom_id"] is not None and chk["custom_id"] not in ALLOWED_CUSTOM_IDS:
        err(f"custom_id {chk['custom_id']!r} not in allowed list")
    t = chk["type"]
    if r["automation"] in ("auto", "semi"):
        if t == "custom":
            if chk["custom_id"] is None:
                err("auto/semi custom rule needs custom_id")
        else:
            m = chk["measure"]
            if m is None or kind not in MEASURES_BY_KIND or m not in MEASURES_BY_KIND[kind]:
                err(f"measure {m!r} not defined for kind {kind!r} in CONTRACTS section 1")
            if t in OPS and chk["op"] != OPS[t]:
                err(f"op {chk['op']!r} inconsistent with type {t!r}")
            if t in ("min", "max", "range") and not _is_num(chk["limit"]):
                err("numeric limit required")
            if t == "range" and not _is_num(chk["limit_max"]):
                err("range needs numeric limit_max")
            if t == "range" and _is_num(chk["limit"]) and _is_num(chk["limit_max"]) and chk["limit"] > chk["limit_max"]:
                err("range limit > limit_max")
            if t == "equals" and chk["limit"] is None:
                err("equals needs limit")
            if chk["tolerance"] is not None and not _is_num(chk["tolerance"]):
                err("tolerance must be numeric|null")
            if chk["custom_id"] is not None:
                err("declarative rule must not set custom_id")
    else:  # manual: informational check allowed, must not claim an unsupported custom id
        pass
    if not isinstance(r["notes"], str):
        err("notes must be a string")
    return errs


def validate_catalogue(cat: dict) -> list[str]:
    """Validate against CONTRACTS.md section 4. Returns a list of problems ([] = valid)."""
    errs: list[str] = []
    if not isinstance(cat, dict):
        return ["catalogue must be an object"]
    if cat.get("schema_version") != "1":
        errs.append("schema_version must be '1'")
    reg = cat.get("regulation")
    if not isinstance(reg, dict) or any(k not in reg for k in ("id", "title", "version", "source_pdf")):
        errs.append("regulation must contain id,title,version,source_pdf")
    rules = cat.get("rules")
    if not isinstance(rules, list) or not rules:
        errs.append("rules must be a non-empty list")
        return errs
    seen: dict[str, int] = {}
    for r in rules:
        if not isinstance(r, dict):
            errs.append("rule is not an object")
            continue
        seen[r.get("id")] = seen.get(r.get("id"), 0) + 1
        errs.extend(validate_rule(r))
    for rid, n in seen.items():
        if n > 1:
            errs.append(f"duplicate rule id {rid} ({n}x)")
    return errs
