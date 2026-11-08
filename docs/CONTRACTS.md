# BIMCheck data contracts (v1)

Conventions: JSON; **metres, m², degrees**; world coordinates **Z-up** (IFC/DWG-world). `null` = unknown (never 0 as
"unknown"). Extra fields are allowed anywhere (put them under `"extra"`), required fields are not optional.
Python: plain `dict`s that are JSON-serialisable (dataclasses/pydantic internally is fine, but the public functions
below take/return dicts).

## 1. BuildingModel  (produced by `bimcheck.ingest.ifc.extract_building_model(path) -> dict`)

```jsonc
{
  "schema_version": "1",
  "source": {"kind": "ifc", "file": "Duplex_A.ifc", "ifc_schema": "IFC2X3", "application": "Autodesk Revit ...",
             "length_unit": "METRE", "length_unit_scale_to_m": 1.0},
  "project": {"name": "...", "site_name": null, "building_name": null},
  "storeys": [ {"id": "<GlobalId>", "name": "Level 1", "index": 0, "elevation": 0.0, "height": 3.0 /*to next storey or null*/,
                "is_underground": false } ],            // sorted by elevation, index 0 = lowest
  "elements": [ Element, ... ],
  "summary": {"counts": {"space": 21, "door": 14, ...}, "warnings": ["..."]}
}
```

### Element
```jsonc
{
  "guid": "2O2Fr$t4X7Zf8NOew3FLOH",
  "express_id": 1234,                       // ifcopenshell step id, for debugging
  "ifc_class": "IfcDoor",
  "kind": "space|wall|slab|roof|door|window|stair|railing|covering|column|beam|other",
  "name": "...", "long_name": null, "object_type": null,
  "storey_id": "<storey GlobalId or null>",
  "bbox": {"min": [x,y,z], "max": [x,y,z]},
  "anchor": [x,y,z],                        // representative point (centroid of footprint / element centre)
  "props": { "IsExternal": true, "FireRating": "..." },   // flattened psets (last wins), raw values
  "measures": { ... kind specific, see below ... },
  "provenance": { "<measure name>": "quantity|property|geometry|inferred" }  // missing measures are simply null
}
```
Allowed provenance, strongest → weakest: `quantity` (IfcElementQuantity), `property` (Pset), `geometry` (computed from
tessellated/B-rep geometry), `inferred` (heuristic, e.g. name-based usage class).

### measures by kind  (all optional → `null` if not derivable)
* **space**: `net_floor_area`, `gross_floor_area`, `perimeter`, `height` (clear floor→ceiling), `floor_z`, `ceiling_z`,
  `min_width` (shorter side of min-area rotated rectangle of footprint), `max_length`, `footprint` (`[[x,y],...]`, CCW,
  closed implicitly), `usage` (`living_room|bedroom|kitchen|bathroom|wc|corridor|hall|stair|storage|balcony|terrace|
  technical|garage|commercial|other`), `usage_source` (`name|property|none`), `door_guids`, `window_guids`,
  `has_exterior_window` (bool|null), `window_area`, `exterior_wall_guids`
* **door**: `width` (clear if known else overall), `height`, `is_external` (bool|null), `is_entrance` (bool|null),
  `space_guids` (spaces connected), `thickness`
* **window**: `width`, `height`, `sill_height` (above storey floor), `area`, `is_external`
* **stair**: `riser_height`, `tread_depth`, `width`, `step_count`, `flight_count`, `total_rise`, `clear_headroom`
* **railing**: `height`, `length`
* **wall**: `thickness`, `length`, `height`, `is_external`
* **slab**: `thickness`, `area`, `is_roof`, `is_floor`
* **roof**: `area`, `max_height_z`
* **covering**: `covering_type` (`ceiling|floor|cladding|...`), `area`

Also required from the IFC extractor: `export_geometry_glb(path, out_path, *, storey_filter=None) -> dict` writing a GLB
where: every IFC product with geometry is **one node named by its GlobalId**, `extras = {"guid","ifc_class","kind",
"storey_id","name"}`; **Y-up already applied** (`(x,y,z)_ifc → (x, z, -y)_gltf`); metres; materials carry the IFC
surface colour (alpha supported) with a neutral fallback; IfcSpace geometry is exported too but with
`extras.kind="space"` (viewer will hide/ghost it). Returns `{"nodes": n, "triangles": t, "bounds": {...ifc-world Z-up}}`.
Viewer-side conversion for any data coordinate: `toViewer([x,y,z]) = [x, z, -y]`.

## 2. DrawingModel  (produced by `bimcheck.ingest.drawing.extract_drawing_model(path, *, layer_roles=None) -> dict`)

```jsonc
{
  "schema_version": "1",
  "source": {"kind": "dwg|dxf", "file": "...", "dwg_version": "AC1024", "units": "m|cm|mm|unknown",
             "unit_scale_to_m": 0.01, "unit_source": "header|dimension-ratio|assumed", "entity_count": 96815},
  "layers": [ {"name": "duvar", "entity_count": 123, "role": "parcel|wall|door|window|stair|room_label|area_label|
               dimension|level_mark|column|grid|furniture|hatch|text|annotation|ignored|unknown",
               "role_confidence": 0.0-1.0, "role_source": "name|geometry|user"} ],
  "views": [ {"id": "v1", "kind": "floor_plan|site_plan|section|elevation|detail|unknown", "name": "ZEMİN KAT PLANI",
              "level_hint": 0 | null, "elevation": null, "bbox": [minx,miny,maxx,maxy]} ],
  "parcel":  {"polygon": [[x,y],...], "area": 640.0, "layer": "arsa", "view_id": "v?", "source": "polyline|hatch"} | null,
  "footprint": {"polygon": [[x,y],...], "area": 120.0, "view_id": "v?", "confidence": 0.7} | null,
  "rooms":   [ {"id": "r1", "view_id": "v1", "name": "SALON", "usage": "<same vocabulary as space.usage>",
                "polygon": [[x,y],...], "area": 24.1, "labelled_area": 24.1|null, "min_width": 3.4, "label_point": [x,y],
                "confidence": 0.8} ],
  "walls":   [ {"view_id","layer","polyline":[[x,y],...],"thickness":0.25|null} ],
  "doors":   [ {"view_id","position":[x,y],"width":0.9,"height":null,"layer":"..."} ],
  "windows": [ ... same ... ],
  "stairs":  [ {"view_id","bbox":[...],"width":1.2|null,"riser_count":null,"tread_depth":0.28|null,"layer":"..."} ],
  "dimensions": [ {"view_id","p1":[x,y],"p2":[x,y],"measurement":3.05,"text":"305","layer":"OLCU"} ],
  "levels":  [ {"view_id","text":"+3.00","elevation":3.0,"position":[x,y]} ],
  "texts":   [ {"text","position":[x,y],"layer","height"} ],           // trimmed to meaningful ones, max ~2000
  "warnings": ["..."]
}
```
Hard requirement: **never silently invent**. If something cannot be derived the field is `null`/`[]` and a `warnings`
entry explains why. Layer roles must be overridable via `layer_roles={"duvar":"wall",...}`.

## 3. ProjectContext  (parcel / plan-note parameters; all optional; supplied by the user or derived from DrawingModel)
```jsonc
{
  "municipality": "kayseri",
  "use": "residential|commercial|mixed|other",          // "mixed" = ground-floor commerce
  "zone_type": "konut|ticaret|karma|sanayi|other",
  "building_order": "detached|adjacent|block",           // ayrık / bitişik / blok
  "parcel_area": 640.0,  "parcel_polygon": [[x,y],...],   // metres, same CRS as building footprint if both present
  "taks": 0.40, "kaks": 1.60, "max_storeys": 4, "max_height": 12.5,
  "front_setback": 5.0, "side_setback": 3.0, "rear_setback": 3.0,   // plan-note values; null → regulation default (Art. 23)
  "front_edge_index": 0,                                  // which parcel edge faces the road (index into polygon edges) or null
  "road_width": 12.0,
  "has_elevator": null, "heating": "central|stove|none|null",
  "is_single_dwelling": false,
  "overrides": { "KBB-28-4": {"limit": 2.5} }            // per-rule threshold overrides
}
```

## 4. Rule catalogue  (`rules/kayseri.rules.json`, produced by S1, consumed by S4)
```jsonc
{
  "schema_version": "1", "regulation": {"id": "kbb-imar-2022", "title": "Kayseri BB İmar Yönetmeliği", "version": "14.02.2022",
                                          "source_pdf": "regulation/kayseri-imar-yonetmeligi-2022-lejantli.pdf"},
  "rules": [ {
    "id": "KBB-28-4",                     // KBB-<article>-<paragraph>[-<item>]
    "article": 28, "paragraph": "4", "item": null,
    "title_tr": "İskân edilen katların iç yüksekliği", "title_en": "Clear height of occupied storeys",
    "text_tr": "<current-in-force text, redline applied>", "page": 14,
    "category": "heights|rooms|circulation|stairs|openings|safety|setbacks|zoning|services|accessibility|other",
    "automation": "auto|semi|manual",     // manual = catalogued but needs human; semi = engine can pre-screen, always 'review' on edge
    "requires": ["building_model"],        // any of building_model|drawing_model|parcel_context
    "severity": "error|warning|info",
    "applies_when": { "building_use": ["residential","mixed"], "min_storeys": null, "max_storeys": null,
                      "storey_kind": null },
    "check": {                              // DECLARATIVE form
      "type": "min|max|range|equals|exists|custom",
      "target": {"kind": "space", "usage_in": ["living_room","bedroom"], "usage_not_in": null, "where": null},
      "measure": "height", "op": ">=", "limit": 2.60, "limit_max": null, "unit": "m", "tolerance": 0.005,
      "limit_by": null,                    // optional lookup, e.g. {"measure":"stair_has_elevator","map":{"true":0.18,"false":0.16}}
      "exceptions": ["Hava maniası olan parsellerde 2.40 m"],       // free text, → shown in UI, may downgrade to review
      "custom_id": null                    // when type=custom: name of the python check function in bimcheck.engine.checks
    },
    "unit_display": "m",
    "revision": {"status": "current|amended|new", "note": "limit changed 2.50→2.60 by 2022 amendment"} | null,
    "notes": "implementation hints / caveats"
  } ]
}
```
Also S1 outputs `regulation/articles.json`: `[{"article":28,"title":"Kat yükseklikleri","page":14,"paragraphs":[{"no":"1","text":"<current>",
"items":[{"key":"a","text":"..."}],"revisions":[{"type":"added|deleted","text":"5.50"}]}]}]`.

## 5. Findings  (produced by `bimcheck.engine.run_check(...)`)

```python
run_check(building_model: dict|None, drawing_model: dict|None, context: dict|None, rules: dict|None = None,
          *, rule_ids: list[str]|None = None) -> dict
```
returns
```jsonc
{
  "schema_version": "1",
  "summary": {"violation": 3, "review": 5, "pass": 40, "not_applicable": 12, "rules_evaluated": 18, "rules_skipped_manual": 30,
              "errors": [ "rule KBB-xx crashed: ..." ]},
  "findings": [ {
    "id": "KBB-28-4:2O2Fr$t4X7Zf8NOew3FLOH",       // stable: rule_id + ":" + element guid (or ":model" / ":parcel")
    "rule_id": "KBB-28-4", "article": 28, "paragraph": "4", "title_tr": "...", "title_en": "...", "category": "heights",
    "status": "violation|review|pass|not_applicable",
    "severity": "error|warning|info",
    "message_en": "Bedroom 'Schlafen' is 2.45 m high; minimum is 2.60 m",
    "message_tr": "...",
    "measured": {"value": 2.45, "unit": "m", "provenance": "geometry"},
    "required": {"op": ">=", "value": 2.60, "unit": "m"},
    "review_reason": null | "missing_measure" | "low_confidence" | "legal_judgement" | "missing_context" | "exception_may_apply",
    "review_hint": "what the human should check",
    "element_guids": ["..."], "storey_id": "...", "storey_name": "...",
    "highlight": [{"guid": "...", "role": "offending|context"}],
    "anchor": [x,y,z],
    "dimensions": [{"p1": [x,y,z], "p2": [x,y,z], "label": "2.45 m", "kind": "linear|area|clearance"}],   // overlay geometry, IFC world Z-up
    "regulation_excerpt": "<text_tr of the rule>",
    "source": "building_model|drawing_model|parcel_context",
    "view_id": null                                    // drawing-based findings reference the DrawingModel view
  } ]
}
```
Statuses: `pass` findings are emitted per checked element so the UI can show them (UI hides them by default).
`review` = engine could not decide alone. `not_applicable` only when a rule's applicability excluded the target
(UI hides by default; engine may emit one summary entry per rule instead of per element).

## 6. Decisions (server-persisted, keyed by finding id)
```jsonc
{ "finding_id": "...", "decision": "accepted_violation|waived|compliant|needs_info", "note": "...", "by": "reviewer", "at": "ISO-8601" }
```

## 7. Server API (S5)
```
POST   /api/projects                         {name} -> {id,...}
GET    /api/projects | /api/projects/{id}
POST   /api/projects/{id}/model              multipart(file=.ifc)  -> ingest + glb + recheck + WS broadcast
POST   /api/projects/{id}/drawing            multipart(file=.dwg|.dxf) -> ingest + recheck
PUT    /api/projects/{id}/context            ProjectContext -> recheck
GET    /api/projects/{id}/building-model | /drawing-model | /context
GET    /api/projects/{id}/geometry.glb
GET    /api/projects/{id}/findings           -> run_check result merged with decisions
PUT    /api/projects/{id}/findings/{fid}/decision   Decision
GET    /api/projects/{id}/report.{json|csv|html|bcf}
GET    /api/rules | /api/regulation/articles | /api/regulation/articles/{n}
PUT    /api/projects/{id}/rule-overrides     {"KBB-28-4": {"limit": 2.5}}
WS     /ws/projects/{id}                     events: {"type":"model_updated"|"findings_updated","diff":{new,resolved,changed}}
GET    /                                     web UI (static from /web)
```
Persistence: `data/projects/{id}/` (files + `state.json`), no external DB.
