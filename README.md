# BIMCheck (MVP)

Checks IFC / DWG building models against the Kayseri İmar Yönetmeliği and lets a reviewer inspect and decide each finding in 3D.

```
pip install -e .
python -m bimcheck serve                      # UI at http://127.0.0.1:8765/  (click a sample, wait ~25 s)
python -m bimcheck check samples/Duplex_A_20110907.ifc          # offline CLI check
python -m bimcheck watch model.ifc --drawing plan.dwg           # re-check on every save
```

Design: `docs/ARCHITECTURE.md`, data formats: `docs/CONTRACTS.md`, rules: `rules/RULES.md`.
Known limits: only 49 of 173 catalogued rules are machine-checked (the rest are listed as manual); DWG room polygons are
unreliable (partitions not closed); setbacks/TAKS/KAKS need parcel parameters (settings drawer) or a drawing with parcel;
Revit/AutoCAD connectors in `connectors/` are untested sketches.
