# Drawing ingest (S3)
`extract_drawing_model(path, layer_roles=None)`; debug: `python -m bimcheck.ingest.drawing f.dwg --json o.json --preview o.png`.
DWG is read by `tools/drawing/dwg_bridge.mjs` (LibreDWG WASM) into `data/cache/dwg-<sha1>-b1.json`; DXF via ezdxf.

Heuristics: layer role = name vocabulary (Turkish/English) demoted by content statistics (e.g. MAHAL holds no room names here);
units = dimension-text magnitude vs header $INSUNITS (header said m, content is cm); views = sheet frames (nested double
rectangles) titled from bottom text, section/elevation sheets split by subtitles, gap clustering when no frames; per-view
`scale_factor` from dimension ratio (1/200 sheets are drawn at 1/4 size => 4); output coordinates are metres in each view's
own frame (raw x unit_scale x scale_factor). Parcel = extended-line polygonize of parcel-layer lines (section marker lines
excluded), cross-checked with "PARSEL ALANI" text. Footprint = 1 m closing of wall/column/plaster (+glazing for ground floor).
Rooms = name text + "A:..m2" text pairing; polygon from eroded free space inside the footprint (low accuracy: partitions are
often not closed in the drawing; check `labelled_area` vs `area`, and `confidence`).
Limits: 3DSOLID content unreadable; doors/windows come from tag texts ("90/220-K2") and block extents only; stairs = bbox only.
