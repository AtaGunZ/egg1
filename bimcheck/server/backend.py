"""Adapter between the server and the ingest / engine / regulation packages.

All heavy imports are lazy so the server starts (and the web UI loads) even when a subsystem is not installed yet;
a missing subsystem surfaces as :class:`BackendUnavailable` (HTTP 503 with a clear message) at the moment it is needed.
Tests inject a stub by subclassing :class:`Backend` and passing it to ``create_app(backend=...)``.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[2]


class BackendUnavailable(RuntimeError):
    """A required subsystem (ingest/engine/regulation) cannot be imported."""


class IngestError(ValueError):
    """The uploaded file could not be read (bad/corrupt/unsupported)."""


def _need(modname: str, attr: str, what: str):
    try:
        mod = __import__(modname, fromlist=[attr])
        return getattr(mod, attr)
    except (ImportError, AttributeError) as exc:  # pragma: no cover - depends on other agents' progress
        raise BackendUnavailable(f"{what} is not available yet ({modname}.{attr}: {exc})") from exc


class Backend:
    rules_path = REPO_ROOT / "rules" / "kayseri.rules.json"
    articles_path = REPO_ROOT / "regulation" / "articles.json"

    # ---- ingest -------------------------------------------------------------------------------------------------
    def extract_building_model(self, path: str) -> dict:
        fn = _need("bimcheck.ingest.ifc", "extract_building_model", "IFC ingest")
        return fn(path)

    def export_geometry_glb(self, path: str, out_path: str) -> dict:
        fn = _need("bimcheck.ingest.ifc", "export_geometry_glb", "IFC geometry export")
        return fn(path, out_path)

    def extract_drawing_model(self, path: str, layer_roles: dict | None = None) -> dict:
        fn = _need("bimcheck.ingest.drawing", "extract_drawing_model", "Drawing ingest")
        return fn(path, layer_roles=layer_roles) if layer_roles else fn(path)

    # ---- engine -------------------------------------------------------------------------------------------------
    def run_check(self, bm: dict | None, dm: dict | None, ctx: dict | None) -> dict:
        fn = _need("bimcheck.engine", "run_check", "Rule engine")
        return fn(bm, dm, ctx)

    def diff_findings(self, old: dict | None, new: dict) -> dict | None:
        """Engine diff if available (None when not), normalised by the caller."""
        try:
            fn = _need("bimcheck.engine", "diff_findings", "diff_findings")
        except BackendUnavailable:
            return None
        return fn(old or {"findings": []}, new)

    # ---- regulation ---------------------------------------------------------------------------------------------
    def rules(self) -> dict:
        if self.rules_path.exists():
            return json.loads(self.rules_path.read_text(encoding="utf-8"))
        try:  # fall back to A's catalogue helper if it exposes one
            mod = __import__("bimcheck.regulation.catalogue", fromlist=["x"])
            for name in ("load_rules", "load_catalogue", "get_rules"):
                if hasattr(mod, name):
                    return getattr(mod, name)()
        except ImportError:
            pass
        raise BackendUnavailable("rule catalogue rules/kayseri.rules.json does not exist yet")

    def articles(self) -> list[dict[str, Any]]:
        if self.articles_path.exists():
            return json.loads(self.articles_path.read_text(encoding="utf-8"))
        raise BackendUnavailable("regulation/articles.json does not exist yet")
