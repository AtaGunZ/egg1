# BIMCheck — Regulation Compliance Checker for BIM / CAD models

## 1. The essence (what was actually envisioned)

An architect or municipal reviewer drops in **(1) a regulation** (here: *Kayseri Büyükşehir Belediyesi İmar
Yönetmeliği*, 2022 amendment-marked PDF) and **(2) a design model** (IFC from Revit/ArchiCAD, or DWG from AutoCAD).
The system:

1. turns the regulation into **machine-checkable rules**, each traceable to an article/paragraph,
2. turns the model into a **normalised building model with real measurements** (not guesses),
3. evaluates the rules and produces **findings**: `violation` / `pass` / `review` (human judgement or missing data),
4. lets a reviewer **click a finding → see the building rendered, the offending element highlighted, the camera flown
   to it, the measurement drawn in 3D, the regulation text next to it → decide right there** (accept / waive / mark
   compliant / request info),
5. optionally re-runs **live** when the author saves/exports from their CAD tool, and exports a **report** (HTML/CSV/JSON/BCF).

The previous prototype (single HTML file, regex IFC parsing, ~4 hard-coded rules, web-ifc 0.0.43 from CDN, wrong
axis orientation) is discarded. Only the idea is kept.

## 2. Why a server + thin connectors (not a standalone HTML page, not a CAD-only plugin)

* IFC geometry/property extraction is best done with **ifcopenshell** (Python): real quantity take-off, polygon
  footprints, boundary relations. DWG needs a converter/parser and 96k-entity drawings are heavy for a browser.
* A CAD plugin alone would lock us to one vendor; the reviewer (municipality) usually does **not** have Revit.
* Therefore: **Python core + FastAPI server + browser UI**, and **connectors** (Revit/ArchiCAD export IFC, AutoCAD
  saves DWG) that only need to *push a file* to `POST /api/projects/{id}/model`. A file-watcher CLI gives
  "real-time" with zero plugin code; native plugins are thin wrappers later.

```
  Revit / ArchiCAD / AutoCAD ──(export/save)──► connector / `bimcheck watch`
                                                        │ POST file
  PDF regulation ─► regulation pipeline ─► rules.json   ▼
                                    ┌───────────── bimcheck server (FastAPI) ─────────────┐
   IFC ─► ingest.ifc ─► BuildingModel + GLB ─┐                                            │
   DWG ─► ingest.drawing ─► DrawingModel ────┼─► engine (rules × models × ProjectContext) ─► Findings
   ProjectContext (parcel/plan notes) ───────┘                    │ WebSocket push        │
                                                                   ▼                       │
                                       Web UI: 3D viewer + review workspace + reports ◄────┘
```

## 3. Subsystems

| # | Subsystem | Package / path | Owner agent |
|---|-----------|----------------|-------------|
| S1 | Regulation pipeline: PDF → revision-aware article text → machine-readable rule catalogue | `bimcheck/regulation/`, `rules/`, `regulation/` | **A** |
| S2 | IFC ingest: ifcopenshell → `BuildingModel` JSON + `geometry.glb` | `bimcheck/ingest/ifc/` | **B** |
| S3 | Drawing ingest: DWG/DXF → `DrawingModel` (parcel, rooms, walls, stairs, dims, layer mapping) | `bimcheck/ingest/drawing/` | **C** |
| S4 | Rule engine + check implementations (+ applicability, `review` logic, ProjectContext) | `bimcheck/engine/` | **D** |
| S5 | Server (projects, uploads, live recheck, decisions, reports) + Web UI (viewer, findings, review workspace) | `bimcheck/server/`, `web/` | **E** |
| S6 | Connectors + CLI (`bimcheck check`, `bimcheck watch`), docs, integration, E2E tests | `bimcheck/cli.py`, `connectors/`, `tests/e2e` | lead |

### What a *proper* product needs per subsystem (gap list vs. the dead prototype)

**S1 Regulation**
* The PDF is a *redline* ("lejantlı": black = unchanged, **red = added**, **grey = deleted**). Plain text extraction
  yields garbage like `5.50 6.50` or `2000 1500`. Must read span colours (PyMuPDF) and emit **current-in-force text**
  plus the revision spans. Wrong here = every threshold is a coin flip.
* Article → paragraph → item structure with stable ids (`KBB-28-4`), page refs, cross-refs to *Planlı Alanlar İmar
  Yönetmeliği* (not in the PDF → flagged as external dependency).
* Rule catalogue: declarative where possible (`min/max/range` on a named measure for an element class under
  applicability conditions), `custom` where logic is needed, and an explicit **automation level**
  (`auto` / `semi` / `manual`) so the UI can honestly say "this article needs a human" instead of silently skipping.
* Rule authoring/override: thresholds editable per project (municipalities differ; plan notes override defaults).

**S2 IFC**
* Correct units (mm/m/ft), IFC2x3 + IFC4, Revit and ArchiCAD quirks.
* Measurements taken from **quantity sets → properties → geometry (fallback)** with a provenance tag per value so the
  engine can downgrade to `review` when only guessed.
* Space polygon, net area, clear height, **min clear width**, usage classification (TR + EN names), adjacency
  (doors/windows bounding each space), exterior-window presence.
* Doors/windows (clear width/height, sill), stairs (riser/tread/width from flights/geometry), railings (height),
  walls (thickness, external), slabs, roof, storey elevations/heights.
* GLB export with per-element nodes named by GlobalId, **Y-up already applied** (the old prototype's orientation bug).

**S3 Drawing**
* DWG (AC1024 = AutoCAD 2010) via LibreDWG-WASM (`@mlightcad/libredwg-web`, already in `node_modules`) or any better
  route that works on Windows without a paid licence. DXF via `ezdxf`.
* Sample `11523-3 mimari ... onaylı.dwg`: 96,815 entities, one model space holding several plans/sections;
  layers `arsa` (parcel), `duvar`, `MAHAL` (room names), `ALAN` (areas), `MERDİVEN`, `KOT` (levels), `OLCU`...
  → needs **layer-role mapping** (auto-suggest from Turkish/English names + geometry heuristics, overridable),
  **drawing segmentation** (which cluster is the ground-floor plan, 1st-floor plan, section, elevation),
  unit detection, room polygon+label association, parcel polygon, footprint.
* Sample `VAZİYET 3D.dwg` is 3D solids/site: only a few polylines/lines usable → extract what exists, report what not.
* Enables **setback (bahçe mesafesi, Art. 23)** and **TAKS/KAKS** checks that IFC alone cannot do.

**S4 Engine**
* Rule × element evaluation, applicability (use, storey count, room usage), unit-safe comparison with tolerance,
  `review` when data missing / low confidence / needs legal interpretation, **never crash on one bad rule**.
* Stable finding ids (same rule+element → same id) so reviewer decisions survive re-checks.
* Findings carry **everything the UI needs**: guids, storey, anchor point, measurement overlay segments, regulation
  excerpt, provenance.

**S5 Server + UI**
* Real 3D viewer: orientation correct, orbit/pan/zoom, view cube, **storey isolation**, **horizontal section cut**,
  per-class toggles (hide ceilings/roofs/slabs), ghost/x-ray others, highlight offenders (red) and context (amber),
  smooth fly-to, 3D measurement lines with labels, element picking → properties.
* Review workspace: list beside the viewer, filters (status/article/storey/category), selected finding shows
  regulation text + measured vs required + decision form (accept/waive/compliant/needs-info + note); decisions persisted.
* Live: re-upload (or watcher) → recheck → WebSocket push → UI diff (new/resolved/changed), decisions preserved.
* Reports: JSON, CSV, standalone HTML, BCF-zip (stretch).
* Project settings: ProjectContext form (use, storeys, TAKS/KAKS, setbacks, road width…), rule threshold overrides.

**S6** CLI + watcher + connector stubs (pyRevit / AutoCAD script that exports & POSTs) + E2E tests on both IFCs and both DWGs.

## 4. Division of labour & integration rules

* Contract-first: **`docs/CONTRACTS.md` is the law.** Agents A–E work in parallel against it; no agent edits another
  agent's directory. If a contract change is needed, write the proposal to `docs/CONTRACT_CHANGES.md` (append only) and
  keep going with the original.
* Everything in **metres**, world coordinates **Z-up** in data; only the GLB is Y-up.
* Each subsystem ships: code, tests (`pytest`), a `README.md` in its directory, and runs on this Windows machine.
* Integration (lead): wire engine↔ingest↔server, E2E on sample files, fix mismatches, final QA in a browser.
