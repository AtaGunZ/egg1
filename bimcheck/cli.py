"""BIMCheck command line.

  python -m bimcheck check model.ifc [--drawing plan.dwg] [--context ctx.json] [--out report.json] [--show pass]
  python -m bimcheck watch model.ifc [--drawing plan.dwg] --server http://127.0.0.1:8765 [--project ID]
  python -m bimcheck serve [--port 8765]

`check` runs fully offline (ingest + engine). `watch` re-uploads a file to a running server every time the file
changes on disk (works with any CAD tool that can export/save IFC or DWG on save -> "real-time" without a plugin).
"""
from __future__ import annotations

import argparse
import json
import mimetypes
import sys
import time
import urllib.request
import uuid
from pathlib import Path


# ---------------------------------------------------------------------------------------------- helpers
def _load_json(p: str | None):
    return json.loads(Path(p).read_text(encoding="utf-8")) if p else None


def _multipart(field: str, path: Path) -> tuple[bytes, str]:
    boundary = uuid.uuid4().hex
    ctype = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
    head = (f'--{boundary}\r\nContent-Disposition: form-data; name="{field}"; filename="{path.name}"\r\n'
            f"Content-Type: {ctype}\r\n\r\n").encode("utf-8")
    body = head + path.read_bytes() + f"\r\n--{boundary}--\r\n".encode()
    return body, f"multipart/form-data; boundary={boundary}"


def _http(method: str, url: str, *, data: bytes | None = None, ctype: str | None = None) -> dict:
    req = urllib.request.Request(url, data=data, method=method)
    if ctype:
        req.add_header("Content-Type", ctype)
    with urllib.request.urlopen(req, timeout=600) as r:  # noqa: S310 (user-supplied local server)
        raw = r.read()
    return json.loads(raw) if raw else {}


def _push(server: str, project: str, kind: str, path: Path) -> dict:
    body, ctype = _multipart("file", path)
    return _http("POST", f"{server.rstrip('/')}/api/projects/{project}/{kind}", data=body, ctype=ctype)


# ---------------------------------------------------------------------------------------------- commands
def cmd_check(a) -> int:
    from bimcheck.engine import run_check
    from bimcheck.ingest.ifc import extract_building_model

    bm = dm = None
    if a.model:
        bm = extract_building_model(a.model)
    if a.drawing:
        from bimcheck.ingest.drawing import extract_drawing_model
        dm = extract_drawing_model(a.drawing)
    result = run_check(bm, dm, _load_json(a.context))
    if a.out:
        Path(a.out).write_text(json.dumps(result, ensure_ascii=False, indent=1), encoding="utf-8")
    s = result["summary"]
    print(f"violations={s['violation']}  review={s['review']}  pass={s['pass']}  "
          f"n/a={s['not_applicable']}  rules={s['rules_evaluated']}  manual-skipped={s['rules_skipped_manual']}")
    for e in s.get("errors", []):
        print("  ENGINE ERROR:", e)
    shown = {"violation", "review"} | ({"pass"} if a.show == "pass" else set())
    for f in result["findings"]:
        if f["status"] in shown:
            print(f"[{f['status'].upper():9}] Madde {f['article']}({f['paragraph']}) {f['message_en']}")
    return 1 if s["violation"] else 0


def cmd_watch(a) -> int:
    server = a.server
    project = a.project
    if not project:
        project = _http("POST", f"{server.rstrip('/')}/api/projects",
                        data=json.dumps({"name": Path(a.model or a.drawing).stem}).encode(),
                        ctype="application/json")["id"]
        print(f"created project {project}  ->  {server.rstrip('/')}/#/{project}")
    watched = [(k, Path(p)) for k, p in (("model", a.model), ("drawing", a.drawing)) if p]
    last: dict[Path, float] = {}
    print("watching", ", ".join(str(p) for _, p in watched), "(Ctrl+C to stop)")
    try:
        while True:
            for kind, p in watched:
                if not p.exists():
                    continue
                m = p.stat().st_mtime
                if last.get(p) != m:
                    time.sleep(a.settle)               # let the CAD tool finish writing
                    if p.stat().st_mtime != m:
                        continue                       # still being written; next tick
                    last[p] = m
                    try:
                        res = _push(server, project, kind, p)
                        print(time.strftime("%H:%M:%S"), f"pushed {p.name}:", res.get("summary", res))
                    except Exception as exc:  # noqa: BLE001
                        print("push failed:", exc, file=sys.stderr)
            time.sleep(a.interval)
    except KeyboardInterrupt:
        return 0


def cmd_serve(a) -> int:
    import uvicorn
    uvicorn.run("bimcheck.server.app:app", host=a.host, port=a.port)
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="bimcheck")
    sub = ap.add_subparsers(dest="cmd", required=True)

    c = sub.add_parser("check", help="ingest + check offline")
    c.add_argument("model", nargs="?", help=".ifc file")
    c.add_argument("--drawing", help=".dwg/.dxf file")
    c.add_argument("--context", help="ProjectContext JSON")
    c.add_argument("--out", help="write full result JSON")
    c.add_argument("--show", choices=["issues", "pass"], default="issues")
    c.set_defaults(fn=cmd_check)

    w = sub.add_parser("watch", help="re-upload on file change")
    w.add_argument("model", nargs="?")
    w.add_argument("--drawing")
    w.add_argument("--server", default="http://127.0.0.1:8765")
    w.add_argument("--project")
    w.add_argument("--interval", type=float, default=1.0)
    w.add_argument("--settle", type=float, default=1.0)
    w.set_defaults(fn=cmd_watch)

    s = sub.add_parser("serve", help="run server + web UI")
    s.add_argument("--host", default="127.0.0.1")
    s.add_argument("--port", type=int, default=8765)
    s.set_defaults(fn=cmd_serve)

    a = ap.parse_args(argv)
    if a.cmd in ("check", "watch") and not (a.model or a.drawing):
        ap.error("give an IFC file and/or --drawing")
    return a.fn(a)


if __name__ == "__main__":
    raise SystemExit(main())
