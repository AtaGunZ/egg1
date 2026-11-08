# bimcheck.engine (S4)

```python
from bimcheck.engine import run_check, diff_findings
res = run_check(building_model, drawing_model, context, rules=None, rule_ids=None)   # CONTRACTS section 5
d = diff_findings(old_res, new_res)   # {"new": [...], "resolved": [...], "changed": [...]}
```

## How rules map to checks
* `check.type` in `min|max|range|equals|exists` -> `declarative.py` (target kind/usage/where, measure, op, limit,
  `limit_by`, tolerance, per-rule `context.overrides[rule_id]` = `limit|limit_max|tolerance|disabled`).
  Windows/doors are matched to a space usage through `space_guids` / the spaces' `window_guids`/`door_guids`.
* `type: custom` -> function registered with `@register("<custom_id>")` in `checks/`. Parameters come from
  `check.extra` (catalogue) merged with `check.params`; `applies_when.extra.zone_type` / `ground_floor_commerce`
  are honoured by the runner. One catalogue rule = one part of a custom check (`extra.part`, `extra.edge`, `extra.scope`).
* Unknown custom id -> one `review` finding (`legal_judgement`, "not implemented"). `automation: manual` rules are
  not evaluated (`summary.rules_skipped_manual`). A crashing rule goes to `summary.errors`, the run continues.
* Applicability: building use (context.use, else inferred from space areas and flagged), min/max storeys (from the
  model), zone type. A rule that does not apply yields ONE `not_applicable` finding (`:model`).
* Finding ids are `rule_id:guid` (or `:model`, `:parcel`, `:parcel:e<i>`, `:dm:<room>`); duplicates get `#n`.

## When is a finding `review`?
`judge.py` is the single place:
* measure missing -> `missing_measure`;
* value `inferred`, or weaker than `check.min_provenance`/`extra.min_provenance`, and within 5/8 % of the limit,
  or a `semi` rule with a geometry-derived value near the limit -> `low_confidence`;
* fails, but a numeric alternative limit in `check.exceptions` (within 80-125 % of the limit) would pass ->
  `exception_may_apply` (switch off per project with `context.exceptions_off=[rule ids]`);
* ambiguous classification (lift present?, common vs in-dwelling stair, door role ...) where the strict limit
  fails and the loose one passes -> `missing_context`/`legal_judgement` (`judge_two`);
* drawing-derived values never produce a hard violation when the room outline is doubtful (confidence < 0.7 or
  labelled area mismatch); a violation that depends on an `inferred` target property (`where`) becomes `review`.

## Adding a check
Create `checks/<module>.py`, import it in `checks/__init__._load`, write `fn(env) -> list[dict]` using
`env.finding(...)`, `env.review(...)`, `env.na(...)`, `judge()`/`judge_two()` and `dims.*` for overlays.
Coordinates in `dimensions` are IFC world Z-up metres.
