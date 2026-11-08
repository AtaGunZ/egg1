# Connectors (CAD → BIMCheck)

BIMCheck's server needs one thing from a CAD tool: **a file**. Every connector therefore only has to export/save and
`POST` it to `/api/projects/{id}/model` (IFC) or `/api/projects/{id}/drawing` (DWG/DXF). The server re-ingests,
re-checks, and pushes the diff to every open browser over WebSocket (decisions are kept — finding ids are stable).

| Connector | Status | How |
|-----------|--------|-----|
| **Any tool** (Revit, ArchiCAD, AutoCAD, FreeCAD, BricsCAD…) | works, no plugin | Export IFC / save DWG to a folder, run `python -m bimcheck watch model.ifc --drawing plan.dwg`. Re-uploads on every save. |
| Revit | `revit/push_to_bimcheck.py` — **untested sketch** (no Revit on the dev machine) | pyRevit button: `doc.Export(folder, name, IFCExportOptions())` then POST. |
| AutoCAD | `autocad/bimcheck_push.lsp` — **untested sketch** | `(c:BIMCHECK)` does QSAVE, then `curl.exe` POST of the DWG (Windows 10+ ships curl). |

Native, in-CAD highlighting (zooming the Revit/AutoCAD view to the failing element) needs a real add-in that polls
`GET /api/projects/{id}/findings` and maps `element_guids` to `ElementId`/handles — the finding payload already carries
GlobalIds and anchors for that. That is roadmap, not built.
