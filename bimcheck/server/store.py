"""File-based project persistence: ``data/projects/{id}/`` (files + state.json). No external DB."""
from __future__ import annotations

import json
import os
import re
import shutil
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ID_RE = re.compile(r"^[A-Za-z0-9_-]{1,64}$")
DECISIONS = {"accepted_violation", "waived", "compliant", "needs_info"}


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _write_json(path: Path, obj: Any) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(obj, ensure_ascii=False, indent=1), encoding="utf-8")
    os.replace(tmp, path)


def _read_json(path: Path, default: Any = None) -> Any:
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return default


class Project:
    """Thin accessor around one project directory."""

    def __init__(self, root: Path):
        self.root = root
        self.id = root.name
        self._lock = threading.RLock()

    # -- paths
    @property
    def glb(self) -> Path: return self.root / "geometry.glb"
    @property
    def uploads(self) -> Path: return self.root / "uploads"

    def _p(self, name: str) -> Path: return self.root / name

    # -- state
    def state(self) -> dict:
        return _read_json(self._p("state.json"), {}) or {}

    def update_state(self, **kw) -> dict:
        with self._lock:
            st = self.state()
            st.update(kw)
            st["updated"] = now_iso()
            _write_json(self._p("state.json"), st)
            return st

    # -- json docs
    def load(self, name: str, default: Any = None) -> Any:
        return _read_json(self._p(name), default)

    def save(self, name: str, obj: Any) -> None:
        with self._lock:
            _write_json(self._p(name), obj)

    def exists(self, name: str) -> bool:
        return self._p(name).exists()

    # -- decisions
    def decisions(self) -> dict[str, dict]:
        return self.load("decisions.json", {}) or {}

    def set_decision(self, fid: str, decision: str | None, note: str = "", by: str = "reviewer") -> dict | None:
        with self._lock:
            decs = self.decisions()
            if decision in (None, "", "none", "clear"):
                decs.pop(fid, None)
                rec = None
            else:
                if decision not in DECISIONS:
                    raise ValueError(f"decision must be one of {sorted(DECISIONS)}")
                rec = {"finding_id": fid, "decision": decision, "note": note or "", "by": by or "reviewer", "at": now_iso()}
                decs[fid] = rec
            self.save("decisions.json", decs)
            return rec


class Store:
    def __init__(self, data_dir: Path):
        self.root = Path(data_dir) / "projects"
        self.root.mkdir(parents=True, exist_ok=True)

    def get(self, pid: str) -> Project | None:
        if not ID_RE.match(pid or ""):
            return None
        p = self.root / pid
        return Project(p) if (p / "state.json").exists() else None

    def create(self, name: str) -> Project:
        pid = uuid.uuid4().hex[:10]
        p = self.root / pid
        p.mkdir(parents=True)
        (p / "uploads").mkdir()
        proj = Project(p)
        proj.save("state.json", {"id": pid, "name": name or "Untitled project", "created": now_iso(), "updated": now_iso(),
                                 "model": None, "drawing": None, "model_version": 0, "drawing_version": 0,
                                 "status": {"stage": "idle", "message": ""}})
        return proj

    def delete(self, pid: str) -> bool:
        proj = self.get(pid)
        if not proj:
            return False
        shutil.rmtree(proj.root, ignore_errors=True)
        return True

    def list(self) -> list[dict]:
        out = []
        for d in self.root.iterdir():
            st = _read_json(d / "state.json")
            if st:
                out.append(st)
        out.sort(key=lambda s: s.get("updated", ""), reverse=True)
        return out
