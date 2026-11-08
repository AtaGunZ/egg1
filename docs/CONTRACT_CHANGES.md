
## S1 (agent A) notes
* Catalogue extras used: `check.extra` (params for custom checks, e.g. `part`, limits tables), `applies_when.extra` (zone_type, building_order, ground_floor_commerce), top-level `extra` (needs, delegates_to, alt_requires, context_tr).
* `check.target.kind` also uses pseudo-kinds `storey`, `building`, `parcel`. For door/window targets `usage_in` = usage of a space listing the element in door_guids/window_guids. `where` = dict of measure==value (e.g. {"is_entrance": true}).
* `requires` = hard prerequisites; alternatives in `extra.alt_requires`.
* Proposals: BuildingModel kinds `ramp` (slope, rise, width) and `elevator` (car width/depth, door width); ProjectContext.zone_type values akaryakit, kucuk_sanayi, konut_disi_kentsel_calisma, kentsel_servis; space usage `arcade`/`janitor`.
* articles.json items may nest (`items` inside item = numbered sub-items "1)"); articles 1001-1004 = GEÇİCİ MADDE 1-4, 58/59 = unnumbered Yürürlük/Yürütme.

## S4 engine (agent D) - notes, no contract change required
* Engine reads optional catalogue fields as written by S1: `check.extra.*` (part/edge/scope/table/formula),
  `applies_when.extra.zone_type|ground_floor_commerce`. Also understands optional `check.min_provenance`, `check.legal_judgement`.
* Optional ProjectContext keys the engine understands beyond CONTRACTS section 3: `road_edge_indices` (extra front-type edges),
  `is_public_building`, `ground_floor_commerce`, `exceptions_off` (list of rule ids whose `exceptions` must not trigger review),
  `hava_maniasi` (false disables the 2.40 m exception of KBB-28-4), `override[rule].tolerance`.
* Extra custom id implemented (not in catalogue yet): `drawing_area_mismatch` (labelled vs computed room area).
* Findings may carry `extra` (dict) with check-specific details (e.g. `parts`, `edge_class`, `footprint_source`).
