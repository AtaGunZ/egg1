# bimcheck.ingest.ifc (S2)

`extract_building_model(path) -> dict` (CONTRACTS section 1) and `export_geometry_glb(path, out, *, storey_filter=None)`.
CLI: `python -m bimcheck.ingest.ifc file.ifc [--json out.json] [--glb out.glb]`.

* Everything in metres / m2 (IfcUnitAssignment applied to quantities, typed psets and geometry).
* Measure source order: `quantity` (IfcElementQuantity) > `property` (Pset / IFC attribute) > `geometry` (ifcopenshell tessellation + shapely) > `inferred`. Missing = null; provenance per measure. Psets win over Revit's IfcStairFlight attributes (written in feet).
* Space extras in `measures`: `geometry_floor_area`, `geometry_height`, `height_min/mean`, `ceiling_sloped`, `min_inscribed_width`; declared vs geometry mismatches are listed in `summary.warnings`.
* Doors: `width` = clear width if known (property, or overall minus 2x LiningThickness -> provenance `inferred`), else overall; see `width_kind`, `overall_width`, `clear_width`.
* Door/window to space links: IfcRelSpaceBoundary, else geometric proximity (`extra.space_link`). External flags: IsExternal > space boundary > host wall > geometry/name heuristics.
* GLB: node per product named by GlobalId with extras; aggregate parents without geometry (IfcStair, IfcRoof) become group nodes. Spaces are translucent. Returned `bounds` exclude IfcSite (`bounds_with_site` includes it).
