"""BIMCheck rule engine (S4).

Public API:
    run_check(building_model, drawing_model, context, rules=None, *, rule_ids=None) -> dict   (CONTRACTS section 5)
    diff_findings(old, new) -> {"new": [...], "resolved": [...], "changed": [...]}
"""
from .diff import diff_findings
from .runner import load_rules, run_check

__all__ = ["run_check", "diff_findings", "load_rules"]
