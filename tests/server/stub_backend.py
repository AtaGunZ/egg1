"""StubBackend: serves the hand-made fixture instead of the real ingest/engine (for tests + early UI development).

``python tests/server/stub_backend.py [port]`` starts a dev server on that port using the stub.
"""
from __future__ import annotations

import copy
import json
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
sys.path.insert(0, str(Path(__file__).parent))

from bimcheck.server.backend import Backend, IngestError  # noqa: E402
import fixture_house as fh  # noqa: E402

FIX = fh.FIX


class StubBackend(Backend):
    def __init__(self):
        fh.write_all()
        self.rules_path = FIX / "rules.json"
        self.articles_path = FIX / "articles.json"
        self.rules_path.write_text(json.dumps({"schema_version": "1", "regulation": {"id": "stub", "title": "Stub regulation"}, "rules": [
            {"id": "KBB-28-4", "article": 28, "paragraph": "4", "title_tr": "Kat yuksekligi", "title_en": "Clear height", "category": "heights",
             "automation": "auto", "requires": ["building_model"], "severity": "error", "text_tr": "Ic yukseklik en az 2.60 m",
             "check": {"type": "min", "measure": "height", "op": ">=", "limit": 2.6, "unit": "m"}},
            {"id": "KBB-99-1", "article": 99, "paragraph": "1", "title_tr": "Elle kontrol", "title_en": "Manual item", "category": "other",
             "automation": "manual", "requires": [], "severity": "info", "text_tr": "...", "check": {"type": "custom", "custom_id": None}}]}), encoding="utf-8")
        self.articles_path.write_text(json.dumps([{"article": 28, "title": "Kat yukseklikleri", "page": 14,
                                                    "paragraphs": [{"no": "4", "text": "Ic yukseklik en az 2.60 m", "items": [], "revisions": []}]}]),
                                      encoding="utf-8")
        self.calls: list[str] = []

    def extract_building_model(self, path):
        self.calls.append("bm")
        if Path(path).read_bytes().startswith(b"ISO-10303-21;\nBROKEN"):
            raise IngestError("corrupt IFC")
        return fh.building_model()

    def export_geometry_glb(self, path, out_path):
        self.calls.append("glb")
        return fh.build_glb(Path(out_path))

    def extract_drawing_model(self, path, layer_roles=None):
        self.calls.append("dm")
        return fh.drawing_model()

    def run_check(self, bm, dm, ctx):
        self.calls.append("check")
        res = copy.deepcopy(fh.findings())
        lim = ((ctx or {}).get("overrides") or {}).get("KBB-28-4", {}).get("limit")
        if lim is not None and lim <= 2.45:
            for f in res["findings"]:
                if f["rule_id"] == "KBB-28-4" and f["status"] == "violation":
                    f["status"] = "pass"
            res["summary"]["violation"] -= 1
            res["summary"]["pass"] += 1
        if not dm:
            res["findings"] = [f for f in res["findings"] if f["source"] != "drawing_model"]
        return res


if __name__ == "__main__":
    import tempfile
    import uvicorn
    from bimcheck.server.app import create_app
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8765
    uvicorn.run(create_app(data_dir=tempfile.mkdtemp(), backend=StubBackend()), host="127.0.0.1", port=port)
