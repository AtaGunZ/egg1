# bimcheck.server

FastAPI server implementing CONTRACTS section 7 + the web UI in `web/` (served at `/`).

Run: `python -m bimcheck.server [--port 8765] [--data DIR]` (data in `data/projects/{id}/`).
Extras beyond the contract: `/api/samples`, `/api/projects/{id}/recheck`, `/context/derive`, `/layer-roles`,
`DELETE/PATCH` project, WS events `status` / `decision_updated`. Reports: json, csv, html, bcf (BCF 2.1, minimal).
Ingest/engine are imported lazily (`backend.py`); missing subsystems give HTTP 503. Tests: `pytest tests/server`
(uses `tests/server/stub_backend.py`, a fixture box-house).
