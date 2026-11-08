"""BIMCheck FastAPI server (CONTRACTS section 7).

Run:  python -m bimcheck.server [--port 8765]      (or ``python -m bimcheck serve``)
"""
from __future__ import annotations

import asyncio
import json
import mimetypes
import os
import re
import shutil
import traceback
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any

from fastapi import Body, FastAPI, File, HTTPException, UploadFile, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles

from . import reports
from .backend import REPO_ROOT, Backend, BackendUnavailable, IngestError
from .bcf import build_bcf
from .store import DECISIONS, Project, Store, now_iso

mimetypes.add_type("application/javascript", ".js")
mimetypes.add_type("application/javascript", ".mjs")
mimetypes.add_type("model/gltf-binary", ".glb")

MAX_UPLOAD = 1024 * 1024 * 1024
SAMPLE_LABELS = {
    "Duplex_A_20110907.ifc": ("Duplex (Revit IFC2x3)", "ifc"),
    "AC20-FZK-Haus.ifc": ("FZK-Haus (IFC4)", "ifc"),
    "mimari-onayli.dwg": ("Approved architectural drawing (DWG)", "drawing"),
    "vaziyet-3d.dwg": ("Site plan 3D (DWG)", "drawing"),
}
OPEN = ("violation", "review")



def _render_pdf_page(pdf: Path, page_no: int, text: str, out: Path, zoom: float = 2.0) -> None:
    """Render one PDF page to PNG; highlight the block of `text` (start/end snippets located with search_for)."""
    import pymupdf
    doc = pymupdf.open(str(pdf))
    try:
        if not 1 <= page_no <= len(doc):
            raise HTTPException(404, f"page {page_no} out of range")
        pg = doc[page_no - 1]
        words = (text or "").split()
        rects = []
        def find(snippet_words, from_y=None):
            """First hit of the longest findable snippet (6..3 words) at/after from_y."""
            for n in (6, 5, 4, 3):
                if len(snippet_words) >= n:
                    q = " ".join(snippet_words[:n]) if from_y is None else " ".join(snippet_words[-n:])
                    found = [r for r in pg.search_for(q) if from_y is None or r.y1 >= from_y]
                    if found:
                        return found[0]
            return None

        head = find(words) if len(words) >= 3 else None
        if head is not None:
            tail = find(words, from_y=head.y0) or head
            rects.append(pymupdf.Rect(pg.rect.x0 + 30, head.y0 - 2, pg.rect.x1 - 30, max(head.y1, tail.y1) + 2))
        for r in rects:
            annot = pg.add_rect_annot(r)
            annot.set_colors(stroke=(1, 0.75, 0), fill=(1, 0.9, 0.2))
            annot.set_opacity(0.28)
            annot.set_border(width=1.5)
            annot.update(opacity=0.28)
        pix = pg.get_pixmap(matrix=pymupdf.Matrix(zoom, zoom), annots=True)
        pix.save(str(out))
    finally:
        doc.close()


class NoCacheStatic(StaticFiles):
    async def get_response(self, path, scope):
        resp = await super().get_response(path, scope)
        resp.headers["Cache-Control"] = "no-cache"
        return resp


def _ids(items) -> list[str]:
    out = []
    for it in items or []:
        if isinstance(it, dict):
            out.append(str(it.get("id") or it.get("finding_id") or (it.get("finding") or {}).get("id") or ""))
        else:
            out.append(str(it))
    return out


def _own_diff(old: dict | None, new: dict) -> dict:
    o = {f["id"]: f for f in (old or {}).get("findings", [])}
    n = {f["id"]: f for f in new.get("findings", [])}
    new_ids = [i for i, f in n.items() if f["status"] in OPEN and (i not in o or o[i]["status"] not in OPEN)]
    resolved = [i for i, f in o.items() if f["status"] in OPEN and (i not in n or n[i]["status"] not in OPEN)]
    changed = []
    for i, f in n.items():
        if i in o and i not in new_ids and f["status"] in OPEN:
            g = o[i]
            if g["status"] != f["status"] or (g.get("measured") or {}).get("value") != (f.get("measured") or {}).get("value"):
                changed.append(i)
    return {"new": new_ids, "resolved": resolved, "changed": changed}


def derive_context(dm: dict | None) -> dict:
    ctx: dict[str, Any] = {}
    src: dict[str, str] = {}
    warnings: list[str] = []
    if not dm:
        return {"context": ctx, "sources": src, "warnings": ["no drawing model uploaded"]}
    parcel, fp = dm.get("parcel"), dm.get("footprint")
    if parcel and parcel.get("area"):
        ctx["parcel_area"] = round(float(parcel["area"]), 2)
        src["parcel_area"] = f"parcel polygon (layer {parcel.get('layer')})"
        if parcel.get("polygon"):
            ctx["parcel_polygon"] = parcel["polygon"]
            src["parcel_polygon"] = "parcel polygon"
    else:
        warnings.append("drawing has no parcel polygon; parcel area unknown")
    if parcel and fp and parcel.get("area") and fp.get("area"):
        ctx["taks"] = round(float(fp["area"]) / float(parcel["area"]), 3)
        src["taks"] = "footprint area / parcel area (derived, check it)"
    elif not fp:
        warnings.append("drawing has no building footprint; TAKS not derived")
    return {"context": ctx, "sources": src, "warnings": warnings}


def create_app(data_dir: str | Path | None = None, backend: Backend | None = None,
               web_dir: str | Path | None = None, samples_dir: str | Path | None = None) -> FastAPI:
    data_dir = Path(data_dir or os.environ.get("BIMCHECK_DATA") or REPO_ROOT / "data")
    web_dir = Path(web_dir or REPO_ROOT / "web")
    samples_dir = Path(samples_dir or REPO_ROOT / "samples")
    backend = backend or Backend()
    store = Store(data_dir)
    pool = ThreadPoolExecutor(max_workers=2, thread_name_prefix="bimcheck-job")
    locks: dict[str, asyncio.Lock] = {}
    sockets: dict[str, set[WebSocket]] = {}

    app = FastAPI(title="BIMCheck", version="0.1")
    app.state.store = store
    app.state.backend = backend

    # ---------------------------------------------------------------------------------------------- helpers
    def proj_or_404(pid: str) -> Project:
        p = store.get(pid)
        if not p:
            raise HTTPException(404, f"project '{pid}' not found")
        return p

    def lock_for(pid: str) -> asyncio.Lock:
        return locks.setdefault(pid, asyncio.Lock())

    async def broadcast(pid: str, event: dict) -> None:
        dead = []
        for ws in list(sockets.get(pid, ())):
            try:
                await ws.send_json(event)
            except Exception:
                dead.append(ws)
        for ws in dead:
            sockets.get(pid, set()).discard(ws)

    async def run(fn, *a):
        return await asyncio.get_running_loop().run_in_executor(pool, lambda: fn(*a))

    async def set_status(p: Project, stage: str, message: str = "", **extra) -> None:
        st = {"stage": stage, "message": message, "at": now_iso(), **extra}
        p.update_state(status=st)
        await broadcast(p.id, {"type": "status", **st})

    def effective_context(p: Project) -> dict:
        ctx = dict(p.load("context.json", {}) or {})
        ov = p.load("overrides.json", {}) or {}
        if ov:
            ctx["overrides"] = ov
        return ctx

    def merged_findings(p: Project) -> dict:
        res = p.load("findings.json") or {"schema_version": "1", "summary": {}, "findings": []}
        decs = p.decisions()
        counts = {k: 0 for k in DECISIONS}
        undecided = 0
        out = []
        for f in res.get("findings", []):
            f = dict(f)
            f["decision"] = decs.get(f["id"])
            if f["decision"]:
                counts[f["decision"]["decision"]] = counts.get(f["decision"]["decision"], 0) + 1
            elif f.get("status") in OPEN:
                undecided += 1
            out.append(f)
        summary = dict(res.get("summary") or {})
        summary["decisions"] = counts
        summary["undecided"] = undecided
        return {**res, "summary": summary, "findings": out}

    def public_state(p: Project) -> dict:
        st = p.state()
        st["has_glb"] = p.glb.exists()
        st["has_findings"] = p.exists("findings.json")
        return st

    # ---- jobs (run in worker threads)
    def job_ingest_ifc(p: Project, src: Path) -> dict:
        bm = backend.extract_building_model(str(src))
        if not isinstance(bm, dict) or "elements" not in bm:
            raise IngestError("IFC ingest returned no building model")
        warnings = list((bm.get("summary") or {}).get("warnings") or [])
        glb_info = None
        tmp = p.root / "geometry.glb.tmp"
        try:
            glb_info = backend.export_geometry_glb(str(src), str(tmp))
            os.replace(tmp, p.glb)
        except BackendUnavailable:
            raise
        except Exception as exc:  # geometry failure must not lose the model data
            warnings.append(f"3D geometry export failed: {exc}")
            if tmp.exists():
                tmp.unlink()
            if p.glb.exists():
                p.glb.unlink()
        p.save("building_model.json", bm)
        return {
            "file": src.name, "uploaded": now_iso(), "ifc_schema": (bm.get("source") or {}).get("ifc_schema"),
            "application": (bm.get("source") or {}).get("application"),
            "project": bm.get("project"), "storeys": bm.get("storeys", []),
            "counts": (bm.get("summary") or {}).get("counts", {}), "warnings": warnings,
            "geometry": glb_info,
        }

    def job_ingest_drawing(p: Project, src: Path) -> dict:
        roles = p.load("layer_roles.json")
        dm = backend.extract_drawing_model(str(src), roles or None)
        if not isinstance(dm, dict):
            raise IngestError("drawing ingest returned no drawing model")
        p.save("drawing_model.json", dm)
        return {
            "file": src.name, "uploaded": now_iso(), "source": dm.get("source"),
            "layers": len(dm.get("layers", [])), "views": dm.get("views", []),
            "has_parcel": bool(dm.get("parcel")), "has_footprint": bool(dm.get("footprint")),
            "rooms": len(dm.get("rooms", [])), "warnings": dm.get("warnings", []),
        }

    def job_check(p: Project) -> dict:
        bm = p.load("building_model.json")
        dm = p.load("drawing_model.json")
        if not bm and not dm:
            return {"result": None, "old": None}
        old = p.load("findings.json")
        result = backend.run_check(bm, dm, effective_context(p))
        try:
            diff = backend.diff_findings(old, result)
            if isinstance(diff, dict) and any(k in diff for k in ("new", "resolved", "changed")):
                diff = {k: _ids(diff.get(k)) if not isinstance(diff.get(k), int) else diff.get(k) for k in ("new", "resolved", "changed")}
            else:
                diff = None
        except Exception:
            diff = None
        if diff is None:
            diff = _own_diff(old, result)
        diff["counts"] = {k: (v if isinstance(v, int) else len(v)) for k, v in diff.items() if k in ("new", "resolved", "changed")}
        diff["initial"] = old is None
        p.save("findings.json", result)
        return {"result": result, "diff": diff}

    async def recheck(p: Project, event_type: str = "findings_updated", **extra) -> dict:
        """Run the engine (caller holds the project lock). Never raises for engine problems."""
        out: dict[str, Any] = {"summary": None, "diff": None, "check_error": None}
        try:
            await set_status(p, "checking", "Running rule engine…")
            r = await run(job_check, p)
            if r["result"] is not None:
                out["summary"], out["diff"] = r["result"].get("summary"), r["diff"]
                p.update_state(check={"at": now_iso(), "summary": out["summary"], "error": None})
        except BackendUnavailable as exc:
            out["check_error"] = str(exc)
        except Exception as exc:
            traceback.print_exc()
            out["check_error"] = f"rule engine failed: {exc}"
        if out["check_error"]:
            p.update_state(check={"at": now_iso(), "summary": None, "error": out["check_error"]})
        await set_status(p, "idle", "", error=out["check_error"])
        await broadcast(p.id, {"type": event_type, "diff": out["diff"], "summary": out["summary"],
                               "check_error": out["check_error"], **extra})
        return out

    async def receive_upload(p: Project, file: UploadFile, kinds: dict[str, bytes | None]) -> Path:
        name = Path(file.filename or "upload").name
        ext = Path(name).suffix.lower()
        if ext not in kinds:
            raise HTTPException(400, f"unsupported file type '{ext or name}'; expected {', '.join(sorted(kinds))}")
        safe = re.sub(r"[^\w.\- ]", "_", name)
        dest = p.uploads / safe
        p.uploads.mkdir(exist_ok=True)
        size = 0
        head = b""
        tmp = dest.with_suffix(dest.suffix + ".part")
        with open(tmp, "wb") as fh:
            while chunk := await file.read(1 << 20):
                if not head:
                    head = chunk[:4096]
                size += len(chunk)
                if size > MAX_UPLOAD:
                    fh.close()
                    tmp.unlink(missing_ok=True)
                    raise HTTPException(413, "file too large")
                fh.write(chunk)
        if size == 0:
            tmp.unlink(missing_ok=True)
            raise HTTPException(400, "uploaded file is empty")
        magic = kinds[ext]
        ok = True
        if ext == ".ifc":
            ok = b"ISO-10303-21" in head
        elif ext == ".dwg":
            ok = head.startswith(b"AC10") or head.startswith(b"MC0") or head.startswith(b"AC1")
        elif ext == ".dxf":
            ok = b"SECTION" in head or b"AutoCAD Binary DXF" in head
        if not ok:
            tmp.unlink(missing_ok=True)
            raise HTTPException(400, f"'{name}' does not look like a valid {ext[1:].upper()} file (bad header)")
        os.replace(tmp, dest)
        return dest

    # ---------------------------------------------------------------------------------------------- misc
    @app.get("/api/health")
    async def health():
        mods = {}
        for label, (m, a) in {"ifc_ingest": ("bimcheck.ingest.ifc", "extract_building_model"),
                              "drawing_ingest": ("bimcheck.ingest.drawing", "extract_drawing_model"),
                              "engine": ("bimcheck.engine", "run_check")}.items():
            try:
                mods[label] = hasattr(__import__(m, fromlist=[a]), a)
            except Exception:
                mods[label] = False
        mods["rules"] = backend.rules_path.exists() if hasattr(backend, "rules_path") else None
        return {"ok": True, "time": now_iso(), "subsystems": mods}

    @app.exception_handler(BackendUnavailable)
    async def _unavail(request, exc):
        return JSONResponse({"detail": str(exc)}, status_code=503)

    @app.exception_handler(IngestError)
    async def _ingest_err(request, exc):
        return JSONResponse({"detail": str(exc)}, status_code=400)

    # ---------------------------------------------------------------------------------------------- samples
    @app.get("/api/samples")
    async def list_samples():
        out = []
        if samples_dir.exists():
            for f in sorted(samples_dir.iterdir()):
                if f.suffix.lower() in (".ifc", ".dwg", ".dxf"):
                    label, kind = SAMPLE_LABELS.get(f.name, (f.stem, "ifc" if f.suffix.lower() == ".ifc" else "drawing"))
                    out.append({"name": f.name, "label": label, "kind": kind, "size": f.stat().st_size,
                                "url": f"/api/samples/{f.name}"})
        return out

    @app.get("/api/samples/{name}")
    async def get_sample(name: str):
        f = samples_dir / Path(name).name
        if f.suffix.lower() not in (".ifc", ".dwg", ".dxf") or not f.is_file():
            raise HTTPException(404, "no such sample")
        return FileResponse(f, media_type="application/octet-stream", filename=f.name)

    # ---------------------------------------------------------------------------------------------- projects
    @app.post("/api/projects")
    async def create_project(body: dict = Body(default_factory=dict)):
        p = store.create(str(body.get("name") or "Untitled project")[:120])
        return public_state(p)

    @app.get("/api/projects")
    async def list_projects():
        return store.list()

    @app.get("/api/projects/{pid}")
    async def get_project(pid: str):
        p = proj_or_404(pid)
        st = public_state(p)
        st["decision_counts"] = merged_findings(p)["summary"].get("decisions")
        return st

    @app.delete("/api/projects/{pid}")
    async def delete_project(pid: str):
        proj_or_404(pid)
        store.delete(pid)
        return {"deleted": pid}

    @app.patch("/api/projects/{pid}")
    async def rename_project(pid: str, body: dict = Body(...)):
        p = proj_or_404(pid)
        if not str(body.get("name") or "").strip():
            raise HTTPException(400, "name required")
        return p.update_state(name=str(body["name"])[:120])

    # ---------------------------------------------------------------------------------------------- uploads
    @app.post("/api/projects/{pid}/model")
    async def upload_model(pid: str, file: UploadFile = File(...)):
        p = proj_or_404(pid)
        async with lock_for(pid):
            await set_status(p, "uploading", "Receiving IFC…")
            try:
                src = await receive_upload(p, file, {".ifc": None})
            except HTTPException:
                await set_status(p, "idle")
                raise
            try:
                await set_status(p, "ingesting", f"Reading {src.name} (geometry + quantities)…")
                info = await run(job_ingest_ifc, p, src)
            except BackendUnavailable:
                await set_status(p, "idle")
                raise
            except Exception as exc:
                await set_status(p, "idle", error=f"IFC ingest failed: {exc}")
                raise HTTPException(400, f"IFC ingest failed: {exc}") from exc
            p.update_state(model=info, model_version=p.state().get("model_version", 0) + 1)
            out = await recheck(p, "model_updated", kind="ifc")
        return {**public_state(p), **out}

    @app.post("/api/projects/{pid}/drawing")
    async def upload_drawing(pid: str, file: UploadFile = File(...)):
        p = proj_or_404(pid)
        async with lock_for(pid):
            await set_status(p, "uploading", "Receiving drawing…")
            try:
                src = await receive_upload(p, file, {".dwg": None, ".dxf": None})
            except HTTPException:
                await set_status(p, "idle")
                raise
            try:
                await set_status(p, "ingesting", f"Reading {src.name} (layers, plans, parcel)…")
                info = await run(job_ingest_drawing, p, src)
            except BackendUnavailable:
                await set_status(p, "idle")
                raise
            except Exception as exc:
                await set_status(p, "idle", error=f"Drawing ingest failed: {exc}")
                raise HTTPException(400, f"Drawing ingest failed: {exc}") from exc
            p.update_state(drawing=info, drawing_version=p.state().get("drawing_version", 0) + 1)
            out = await recheck(p, "model_updated", kind="drawing")
        return {**public_state(p), **out}

    @app.put("/api/projects/{pid}/layer-roles")
    async def put_layer_roles(pid: str, body: dict = Body(...)):
        p = proj_or_404(pid)
        p.save("layer_roles.json", body)
        ups = sorted(p.uploads.glob("*.dwg")) + sorted(p.uploads.glob("*.dxf"))
        name = (p.state().get("drawing") or {}).get("file")
        src = next((u for u in ups if u.name == re.sub(r"[^\w.\- ]", "_", name or "")), None)
        if not src:
            raise HTTPException(400, "no drawing uploaded yet")
        async with lock_for(pid):
            await set_status(p, "ingesting", "Re-reading drawing with new layer roles…")
            try:
                info = await run(job_ingest_drawing, p, src)
            except Exception as exc:
                await set_status(p, "idle", error=str(exc))
                raise HTTPException(400, f"Drawing ingest failed: {exc}") from exc
            p.update_state(drawing=info, drawing_version=p.state().get("drawing_version", 0) + 1)
            out = await recheck(p, "model_updated", kind="drawing")
        return {**public_state(p), **out}

    @app.post("/api/projects/{pid}/recheck")
    async def post_recheck(pid: str):
        p = proj_or_404(pid)
        async with lock_for(pid):
            out = await recheck(p)
        return out

    # ---------------------------------------------------------------------------------------------- data getters
    def json_file(p: Project, name: str, what: str) -> FileResponse:
        path = p.root / name
        if not path.exists():
            raise HTTPException(404, f"no {what} uploaded yet")
        return FileResponse(path, media_type="application/json", headers={"Cache-Control": "no-cache"})

    @app.get("/api/projects/{pid}/building-model")
    async def get_bm(pid: str):
        return json_file(proj_or_404(pid), "building_model.json", "building model")

    @app.get("/api/projects/{pid}/drawing-model")
    async def get_dm(pid: str):
        return json_file(proj_or_404(pid), "drawing_model.json", "drawing")

    @app.get("/api/projects/{pid}/geometry.glb")
    async def get_glb(pid: str):
        p = proj_or_404(pid)
        if not p.glb.exists():
            raise HTTPException(404, "no 3D geometry available (upload an IFC model)")
        return FileResponse(p.glb, media_type="model/gltf-binary", headers={"Cache-Control": "no-cache"})

    @app.get("/api/projects/{pid}/context")
    async def get_context(pid: str):
        return effective_context(proj_or_404(pid))

    @app.get("/api/projects/{pid}/context/derive")
    async def get_context_derive(pid: str):
        return derive_context(proj_or_404(pid).load("drawing_model.json"))

    @app.put("/api/projects/{pid}/context")
    async def put_context(pid: str, body: dict = Body(...)):
        p = proj_or_404(pid)
        body = dict(body)
        async with lock_for(pid):
            if "overrides" in body:
                ov = body.pop("overrides") or {}
                if not isinstance(ov, dict):
                    raise HTTPException(400, "overrides must be an object")
                p.save("overrides.json", ov)
            p.save("context.json", {k: v for k, v in body.items() if v is not None})
            out = await recheck(p)
        return {"context": effective_context(p), **out}

    @app.put("/api/projects/{pid}/rule-overrides")
    async def put_overrides(pid: str, body: dict = Body(...)):
        p = proj_or_404(pid)
        for k, v in body.items():
            if not isinstance(v, dict):
                raise HTTPException(400, f"override for {k} must be an object like {{\"limit\": 2.5}}")
        async with lock_for(pid):
            p.save("overrides.json", body)
            out = await recheck(p)
        return {"overrides": body, **out}

    @app.get("/api/projects/{pid}/rule-overrides")
    async def get_overrides(pid: str):
        return proj_or_404(pid).load("overrides.json", {}) or {}

    # ---------------------------------------------------------------------------------------------- findings
    @app.get("/api/projects/{pid}/findings")
    async def get_findings(pid: str):
        return merged_findings(proj_or_404(pid))

    @app.put("/api/projects/{pid}/findings/{fid:path}/decision")
    async def put_decision(pid: str, fid: str, body: dict = Body(...)):
        p = proj_or_404(pid)
        try:
            rec = p.set_decision(fid, body.get("decision"), str(body.get("note") or ""), str(body.get("by") or "reviewer"))
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc
        await broadcast(pid, {"type": "decision_updated", "finding_id": fid, "decision": rec})
        return {"finding_id": fid, "decision": rec}

    @app.delete("/api/projects/{pid}/findings/{fid:path}/decision")
    async def del_decision(pid: str, fid: str):
        p = proj_or_404(pid)
        p.set_decision(fid, None)
        await broadcast(pid, {"type": "decision_updated", "finding_id": fid, "decision": None})
        return {"finding_id": fid, "decision": None}

    # ---------------------------------------------------------------------------------------------- reports
    @app.get("/api/projects/{pid}/report.{fmt}")
    async def report(pid: str, fmt: str, all: bool = False, status: str | None = None):
        p = proj_or_404(pid)
        mf = merged_findings(p)
        st = p.state()
        base = re.sub(r"[^\w\-]+", "_", st.get("name") or "report")
        statuses = set(status.split(",")) if status else None
        if fmt == "json":
            body = json.dumps({"project": st, "context": effective_context(p), **mf}, ensure_ascii=False, indent=1)
            return Response(body, media_type="application/json",
                            headers={"Content-Disposition": f'attachment; filename="{base}.report.json"'})
        sel = reports.select(mf["findings"], all, statuses)
        if fmt == "csv":
            return Response(reports.to_csv(sel), media_type="text/csv; charset=utf-8",
                            headers={"Content-Disposition": f'attachment; filename="{base}.csv"'})
        if fmt == "html":
            return Response(reports.to_html(st, sel, mf["findings"], mf.get("summary")), media_type="text/html; charset=utf-8")
        if fmt == "bcf":
            bm = p.load("building_model.json")
            sel = [f for f in sel if f["status"] in OPEN]
            data = await run(build_bcf, st, sel, bm)
            return Response(data, media_type="application/octet-stream",
                            headers={"Content-Disposition": f'attachment; filename="{base}.bcfzip"'})
        raise HTTPException(404, "report format must be json, csv, html or bcf")

    # ---------------------------------------------------------------------------------------------- regulation
    @app.get("/api/rules")
    async def get_rules():
        return backend.rules()

    @app.get("/api/regulation/articles")
    async def get_articles():
        return [{"article": a.get("article"), "title": a.get("title"), "page": a.get("page")} for a in backend.articles()]

    @app.get("/api/regulation/pdf")
    async def get_regulation_pdf():
        pdf = REPO_ROOT / "regulation" / "kayseri-imar-yonetmeligi-2022-lejantli.pdf"
        if not pdf.exists():
            raise HTTPException(404, "regulation PDF not found")
        return FileResponse(pdf, media_type="application/pdf", headers={"Content-Disposition": 'inline; filename="regulation.pdf"'})

    @app.get("/api/regulation/page/{page}.png")
    async def get_regulation_page(page: int, rule: str | None = None):
        """The real PDF page rendered as an image, with the text of `rule` highlighted (screenshot of the source)."""
        pdf = REPO_ROOT / "regulation" / "kayseri-imar-yonetmeligi-2022-lejantli.pdf"
        if not pdf.exists():
            raise HTTPException(404, "regulation PDF not found")
        key = re.sub(r"[^A-Za-z0-9_.-]", "_", rule or "plain")
        cache = REPO_ROOT / "data" / "cache" / "regpages"
        out = cache / f"p{page}-{key}-v2.png"
        if not out.exists():
            text = ""
            if rule:
                for r in backend.rules().get("rules", []):
                    if r.get("id") == rule:
                        text = r.get("text_tr") or ""
                        break
            cache.mkdir(parents=True, exist_ok=True)
            await asyncio.get_running_loop().run_in_executor(None, _render_pdf_page, pdf, page, text, out)
        return FileResponse(out, media_type="image/png")

    @app.get("/api/regulation/articles/{n}")
    async def get_article(n: int):
        for a in backend.articles():
            if a.get("article") == n:
                return a
        raise HTTPException(404, f"article {n} not found")

    # ---------------------------------------------------------------------------------------------- websocket
    @app.websocket("/ws/projects/{pid}")
    async def ws_project(ws: WebSocket, pid: str):
        p = store.get(pid)
        if not p:
            await ws.close(code=4404)
            return
        await ws.accept()
        sockets.setdefault(pid, set()).add(ws)
        try:
            await ws.send_json({"type": "hello", **(p.state().get("status") or {"stage": "idle"})})
            while True:
                msg = await ws.receive_text()
                if msg == "ping":
                    await ws.send_text("pong")
        except WebSocketDisconnect:
            pass
        except Exception:
            pass
        finally:
            sockets.get(pid, set()).discard(ws)

    # ---------------------------------------------------------------------------------------------- web UI
    if web_dir.exists():
        app.mount("/", NoCacheStatic(directory=str(web_dir), html=True), name="web")
    return app


app = create_app()
