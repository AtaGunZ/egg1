"""Low-level drawing readers: DWG (via LibreDwg-WASM bridge) and DXF (via ezdxf) -> normalised `RawDrawing`.

Normalised entity dicts (all coordinates in drawing units, WCS where feasible):

    {"t": "LINE",   "layer", "p1": (x, y), "p2": (x, y)}
    {"t": "POLY",   "layer", "pts": [(x, y, bulge), ...], "closed": bool}
    {"t": "CIRCLE", "layer", "c": (x, y), "r": r}
    {"t": "ARC",    "layer", "c", "r", "a0", "a1"}              # radians, counter-clockwise
    {"t": "ELLIPSE","layer", "c", "major": (dx, dy), "ratio", "a0", "a1"}   # parametric angles
    {"t": "TEXT",   "layer", "text", "pos": (x, y), "h", "rot", "mtext": bool}
    {"t": "HATCH",  "layer", "paths": [[(x, y), ...], ...], "solid": bool, "pattern": str}
    {"t": "INSERT", "layer", "name", "pos", "sx", "sy", "rot", "attribs": [{"tag","text","pos"}], "cols","rows","dx","dy"}
    {"t": "DIM",    "layer", "p1", "p2", "defpt", "textpos", "measurement", "text", "dtype", "rot"}
    {"t": "SOLID",  "layer", "pts"}
    {"t": "SPLINE", "layer", "pts"}                              # control polygon (approximation)
    {"t": "LEADER", "layer", "pts"}
    {"t": "OTHER",  "layer", "type": "3DSOLID"}                  # counted only
"""
from __future__ import annotations

import hashlib
import json
import math
import os
import re
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

BRIDGE_VERSION = 1
REPO_ROOT = Path(__file__).resolve().parents[3]
BRIDGE_SCRIPT = REPO_ROOT / "tools" / "drawing" / "dwg_bridge.mjs"
CACHE_DIR = REPO_ROOT / "data" / "cache"


@dataclass
class RawDrawing:
    kind: str                       # "dwg" | "dxf"
    file: str
    version: str | None
    header: dict[str, Any]
    layers: list[dict[str, Any]]
    blocks: dict[str, list[dict]]   # name -> normalised entities
    block_base: dict[str, tuple[float, float]]
    entities: list[dict]            # modelspace, normalised
    warnings: list[str] = field(default_factory=list)
    raw_type_counts: dict[str, int] = field(default_factory=dict)
    total_entity_count: int = 0     # modelspace + (non-anonymous) block entities as reported by the file


# ----------------------------------------------------------------------------------------------------------------
# text helpers
# ----------------------------------------------------------------------------------------------------------------
_MTEXT_FONT = re.compile(r"\\[fFcCHhWwQqTtAa][^;\\{}]*;")
_MTEXT_OTHER = re.compile(r"\\[pP][^;]*;")
_MTEXT_UL = re.compile(r"\\[LlOoKk]")


def clean_mtext(s: str) -> str:
    """Strip MTEXT formatting codes (fonts, colours, heights, underline), keep \\P as newline."""
    if not s:
        return ""
    s = s.replace("\\P", "\n").replace("\\~", " ")
    s = _MTEXT_FONT.sub("", s)
    s = _MTEXT_OTHER.sub("", s)
    s = _MTEXT_UL.sub("", s)
    s = re.sub(r"\\S([^;^]*)[/^#]([^;]*);", r"\1/\2", s)  # stacked fractions
    s = s.replace("{", "").replace("}", "").replace("\\\\", "\\")
    # %%c %%d %%p and unicode escapes
    s = s.replace("%%c", "Ø").replace("%%C", "Ø").replace("%%d", "°").replace("%%D", "°").replace("%%p", "±").replace("%%P", "±")
    s = re.sub(r"\\U\+([0-9A-Fa-f]{4})", lambda m: chr(int(m.group(1), 16)), s)
    return s.strip()


def clean_text(s: str) -> str:
    if not s:
        return ""
    s = s.replace("%%c", "Ø").replace("%%C", "Ø").replace("%%d", "°").replace("%%D", "°").replace("%%p", "±").replace("%%P", "±")
    s = re.sub(r"\\U\+([0-9A-Fa-f]{4})", lambda m: chr(int(m.group(1), 16)), s)
    return s.strip()


# ----------------------------------------------------------------------------------------------------------------
# DWG bridge
# ----------------------------------------------------------------------------------------------------------------
def file_sha1(path: str | os.PathLike) -> str:
    h = hashlib.sha1()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def run_bridge(path: str | os.PathLike, cache_dir: Path | None = None, force: bool = False) -> Path:
    """Convert a DWG to bridge JSON (cached by file hash). Returns the JSON path."""
    cache_dir = Path(cache_dir) if cache_dir else CACHE_DIR
    cache_dir.mkdir(parents=True, exist_ok=True)
    key = file_sha1(path)
    out = cache_dir / f"dwg-{key[:16]}-b{BRIDGE_VERSION}.json"
    if out.exists() and out.stat().st_size > 0 and not force:
        return out
    node = os.environ.get("BIMCHECK_NODE", "node")
    tmp = out.with_suffix(".tmp")
    cmd = [node, str(BRIDGE_SCRIPT), str(path), str(tmp)]
    try:
        proc = subprocess.run(cmd, cwd=str(REPO_ROOT), capture_output=True, text=True, timeout=900, encoding="utf-8", errors="replace")
    except FileNotFoundError as e:  # pragma: no cover
        raise RuntimeError("Node.js not found; DWG reading requires `node` on PATH (set BIMCHECK_NODE)") from e
    if proc.returncode != 0 or not tmp.exists():
        raise RuntimeError(f"DWG bridge failed (exit {proc.returncode}): {proc.stderr.strip()[-800:]}")
    os.replace(tmp, out)
    return out


def _p2(v) -> tuple[float, float]:
    return (float(v[0]), float(v[1]))


def _edge_pts(edge: dict, n_arc: int = 24) -> list[tuple[float, float]]:
    """Flatten a libredwg hatch edge (types: 1 line, 2 circular arc, 3 elliptic arc, 4 spline)."""
    t = edge.get("type")
    if t == 1:
        return [_p2(edge["start"]), _p2(edge["end"])]
    if t == 2:
        c = edge.get("center")
        r = edge.get("radius")
        if c is None or r is None:
            return []
        a0, a1 = edge.get("startAngle", 0.0), edge.get("endAngle", 2 * math.pi)
        ccw = edge.get("isCCW", edge.get("isCounterClockwise", True))
        if not ccw:
            a0, a1 = 2 * math.pi - a0, 2 * math.pi - a1
            if a1 > a0:
                a1 -= 2 * math.pi
        elif a1 < a0:
            a1 += 2 * math.pi
        return [(c[0] + r * math.cos(a0 + (a1 - a0) * i / n_arc), c[1] + r * math.sin(a0 + (a1 - a0) * i / n_arc)) for i in range(n_arc + 1)]
    if t == 3:
        c, m = edge.get("center"), edge.get("end") or edge.get("majorAxis") or edge.get("major")
        if c is None or m is None:
            return []
        ratio = edge.get("minorToMajorRatio", edge.get("axisRatio", 1.0))
        a0, a1 = edge.get("startAngle", 0.0), edge.get("endAngle", 2 * math.pi)
        if a1 < a0:
            a1 += 2 * math.pi
        mx, my = m[0], m[1]
        return [(c[0] + mx * math.cos(a0 + (a1 - a0) * i / n_arc) - ratio * my * math.sin(a0 + (a1 - a0) * i / n_arc),
                 c[1] + my * math.cos(a0 + (a1 - a0) * i / n_arc) + ratio * mx * math.sin(a0 + (a1 - a0) * i / n_arc)) for i in range(n_arc + 1)]
    if t == 4:
        pts = edge.get("fitPoints") or edge.get("controlPoints") or []
        return [_p2(p) for p in pts]
    return []


def bulge_points(pts, closed: bool, seg_angle: float = math.radians(10)) -> list[tuple[float, float]]:
    """Flatten (x, y, bulge) vertices into a plain polyline."""
    n = len(pts)
    if n == 0:
        return []
    out: list[tuple[float, float]] = []
    last = n if closed else n - 1
    for i in range(last):
        x0, y0, b = pts[i][0], pts[i][1], (pts[i][2] if len(pts[i]) > 2 else 0.0)
        x1, y1 = pts[(i + 1) % n][0], pts[(i + 1) % n][1]
        out.append((x0, y0))
        if b and abs(b) > 1e-9:
            theta = 4 * math.atan(b)  # signed included angle
            chord = math.hypot(x1 - x0, y1 - y0)
            if chord < 1e-12:
                continue
            r = chord / (2 * math.sin(abs(theta) / 2))
            mx, my = (x0 + x1) / 2, (y0 + y1) / 2
            h = math.sqrt(max(r * r - (chord / 2) ** 2, 0.0))
            nx, ny = -(y1 - y0) / chord, (x1 - x0) / chord  # left normal
            sgn = 1 if b > 0 else -1
            # centre lies on the left of the chord for ccw (b>0) arcs when |theta|<pi
            if abs(theta) < math.pi:
                cx, cy = mx + nx * h * sgn, my + ny * h * sgn
            else:
                cx, cy = mx - nx * h * sgn, my - ny * h * sgn
            a0 = math.atan2(y0 - cy, x0 - cx)
            steps = max(int(abs(theta) / seg_angle), 1)
            for k in range(1, steps):
                a = a0 + theta * k / steps
                out.append((cx + r * math.cos(a), cy + r * math.sin(a)))
    if not closed:
        out.append((pts[-1][0], pts[-1][1]))
    return out


def _chain(parts: list[list[tuple[float, float]]]) -> list[tuple[float, float]]:
    """Join edge point lists end-to-start (flipping edges when needed) into one polyline."""
    pl: list[tuple[float, float]] = []
    for ep in parts:
        if not ep:
            continue
        if pl:
            d0 = math.hypot(pl[-1][0] - ep[0][0], pl[-1][1] - ep[0][1])
            d1 = math.hypot(pl[-1][0] - ep[-1][0], pl[-1][1] - ep[-1][1])
            if d1 < d0:
                ep = ep[::-1]
                d0 = d1
            pl.extend(ep[1:] if d0 < 1e-6 else ep)
        else:
            pl.extend(ep)
    return pl


def _norm_dwg_entity(e: dict) -> dict | None:
    t = e.get("type")
    layer = e.get("layer", "0")
    if t == "LINE":
        return {"t": "LINE", "layer": layer, "p1": _p2(e["startPoint"]), "p2": _p2(e["endPoint"]), "z": (e["startPoint"][2] if len(e["startPoint"]) > 2 else 0.0)}
    if t == "LWPOLYLINE":
        flag = e.get("flag", 0)
        closed = bool(flag & 512) or bool(flag & 1)
        pts = [(v[0], v[1], v[2] if len(v) > 2 else 0.0) for v in e.get("vertices", [])]
        ent = {"t": "POLY", "layer": layer, "pts": pts, "closed": closed}
        if e.get("constantWidth"):
            ent["width"] = e["constantWidth"]
        return ent
    if t == "POLYLINE" or t == "POLYLINE_2D":
        pts = [(v[0], v[1], v[2] if len(v) > 2 else 0.0) for v in e.get("vertices", [])]
        return {"t": "POLY", "layer": layer, "pts": pts, "closed": bool(e.get("flag", 0) & 1)}
    if t == "CIRCLE":
        return {"t": "CIRCLE", "layer": layer, "c": _p2(e["center"]), "r": float(e["radius"])}
    if t == "ARC":
        return {"t": "ARC", "layer": layer, "c": _p2(e["center"]), "r": float(e["radius"]), "a0": float(e["startAngle"]), "a1": float(e["endAngle"])}
    if t == "ELLIPSE":
        return {"t": "ELLIPSE", "layer": layer, "c": _p2(e["center"]), "major": _p2(e["majorAxisEndPoint"]), "ratio": float(e["axisRatio"]),
                "a0": float(e.get("startAngle", 0.0)), "a1": float(e.get("endAngle", 2 * math.pi))}
    if t == "TEXT":
        return {"t": "TEXT", "layer": layer, "text": clean_text(e.get("text", "")), "pos": _p2(e["startPoint"]), "h": float(e.get("textHeight") or 0),
                "rot": float(e.get("rotation") or 0), "mtext": False}
    if t == "MTEXT":
        return {"t": "TEXT", "layer": layer, "text": clean_mtext(e.get("text", "")), "pos": _p2(e["insertionPoint"]), "h": float(e.get("textHeight") or 0),
                "rot": float(e.get("rotation") or 0), "mtext": True}
    if t == "ATTRIB" or t == "ATTDEF":
        tx = e.get("text") or {}
        if isinstance(tx, dict) and tx.get("text") is not None:
            return {"t": "TEXT", "layer": layer, "text": clean_text(tx.get("text", "")), "pos": _p2(tx.get("startPoint", [0, 0])),
                    "h": float(tx.get("textHeight") or 0), "rot": float(tx.get("rotation") or 0), "mtext": False, "tag": e.get("tag")}
        return None
    if t == "HATCH":
        paths = []
        for p in e.get("boundaryPaths", []):
            if "vertices" in p and p["vertices"]:
                pts = [(v[0], v[1], v[2] if len(v) > 2 else 0.0) for v in p["vertices"]]
                paths.append(bulge_points(pts, True))
            elif "edges" in p:
                pl = _chain([_edge_pts(ed) for ed in p["edges"]])
                if len(pl) >= 3:
                    paths.append(pl)
        return {"t": "HATCH", "layer": layer, "paths": paths, "solid": bool(e.get("solidFill")), "pattern": e.get("patternName", "")}
    if t == "INSERT":
        ins = {"t": "INSERT", "layer": layer, "name": e.get("name", ""), "pos": _p2(e["insertionPoint"]), "sx": float(e.get("xScale", 1) or 1),
               "sy": float(e.get("yScale", 1) or 1), "rot": float(e.get("rotation") or 0), "cols": int(e.get("columnCount") or 0) or 1,
               "rows": int(e.get("rowCount") or 0) or 1, "dx": float(e.get("columnSpacing") or 0), "dy": float(e.get("rowSpacing") or 0), "attribs": []}
        for a in e.get("attribs", []) or []:
            na = _norm_dwg_entity(a)
            if na and na["t"] == "TEXT":
                ins["attribs"].append({"tag": a.get("tag"), "text": na["text"], "pos": na["pos"]})
        return ins
    if t == "DIMENSION":
        mt = clean_mtext(e.get("text", "") or "")
        dt = int(e.get("dimensionType", 0)) & 7  # 0 linear/rotated, 1 aligned, 2 angular, 3 diameter, 4 radius, 5 angular 3pt, 6 ordinate
        d = {"t": "DIM", "layer": layer, "p1": _p2(e.get("subDefinitionPoint1", [0, 0])), "p2": _p2(e.get("subDefinitionPoint2", [0, 0])),
             "defpt": _p2(e.get("definitionPoint", [0, 0])), "textpos": _p2(e.get("textPoint", [0, 0])),
             "measurement": float(e.get("measurement", 0) or 0), "text": mt, "dtype": dt, "rot": float(e.get("rotationAngle", 0) or 0),
             "block": e.get("name")}
        return d
    if t == "SOLID" or t == "TRACE":
        return {"t": "SOLID", "layer": layer, "pts": [_p2(e[k]) for k in ("corner1", "corner2", "corner3", "corner4") if k in e]}
    if t == "SPLINE":
        pts = e.get("fitPoints") or e.get("controlPoints") or []
        return {"t": "SPLINE", "layer": layer, "pts": [_p2(p) for p in pts]}
    if t == "LEADER":
        return {"t": "LEADER", "layer": layer, "pts": [_p2(p) for p in e.get("vertices", [])]}
    if t == "3DFACE":
        pts = [e[k] for k in ("corner1", "corner2", "corner3", "corner4") if k in e]
        return {"t": "3DFACE", "layer": layer, "pts3": [list(map(float, p[:3])) for p in pts]}
    if t == "POINT":
        return {"t": "POINT", "layer": layer, "pos": _p2(e.get("position", [0, 0]))}
    return {"t": "OTHER", "layer": layer, "type": t}


def load_dwg(path: str | os.PathLike, cache_dir: Path | None = None) -> RawDrawing:
    jp = run_bridge(path, cache_dir)
    with open(jp, "r", encoding="utf-8") as f:
        d = json.load(f)
    counts: dict[str, int] = {}
    ents: list[dict] = []
    for e in d["modelspace"]:
        counts[e["type"]] = counts.get(e["type"], 0) + 1
        n = _norm_dwg_entity(e)
        if n is not None:
            ents.append(n)
    blocks: dict[str, list[dict]] = {}
    base: dict[str, tuple[float, float]] = {}
    nblk = 0
    for name, b in d["blocks"].items():
        lst = []
        for e in b["entities"]:
            n = _norm_dwg_entity(e)
            if n is not None:
                lst.append(n)
        blocks[name] = lst
        base[name] = _p2(b.get("base") or [0, 0])
        if not name.startswith("*"):
            nblk += len(b["entities"])
    layers = [{"name": l["name"], "color": l.get("color"), "frozen": l.get("frozen", False), "off": l.get("off", False)} for l in d["layers"]]
    rd = RawDrawing(kind="dwg", file=os.path.basename(str(path)), version=d.get("dwg_version"), header=d.get("header", {}), layers=layers,
                    blocks=blocks, block_base=base, entities=ents, raw_type_counts=counts)
    rd.total_entity_count = len(d["modelspace"]) + sum(len(b["entities"]) for b in d["blocks"].values())
    return rd


# ----------------------------------------------------------------------------------------------------------------
# DXF (ezdxf)
# ----------------------------------------------------------------------------------------------------------------
def _norm_dxf_entity(e) -> dict | None:  # pragma: no cover - exercised by DXF tests
    t = e.dxftype()
    layer = e.dxf.layer if e.dxf.hasattr("layer") else "0"
    try:
        if t == "LINE":
            return {"t": "LINE", "layer": layer, "p1": (e.dxf.start.x, e.dxf.start.y), "p2": (e.dxf.end.x, e.dxf.end.y), "z": e.dxf.start.z}
        if t == "LWPOLYLINE":
            pts = [(x, y, b) for x, y, b in e.get_points("xyb")]
            return {"t": "POLY", "layer": layer, "pts": pts, "closed": bool(e.closed)}
        if t == "POLYLINE":
            if e.is_3d_polyline or e.is_polygon_mesh or e.is_poly_face_mesh:
                return {"t": "OTHER", "layer": layer, "type": "POLYLINE3D"}
            pts = [(v.dxf.location.x, v.dxf.location.y, v.dxf.bulge if v.dxf.hasattr("bulge") else 0.0) for v in e.vertices]
            return {"t": "POLY", "layer": layer, "pts": pts, "closed": bool(e.is_closed)}
        if t == "CIRCLE":
            return {"t": "CIRCLE", "layer": layer, "c": (e.dxf.center.x, e.dxf.center.y), "r": e.dxf.radius}
        if t == "ARC":
            return {"t": "ARC", "layer": layer, "c": (e.dxf.center.x, e.dxf.center.y), "r": e.dxf.radius,
                    "a0": math.radians(e.dxf.start_angle), "a1": math.radians(e.dxf.end_angle)}
        if t == "ELLIPSE":
            return {"t": "ELLIPSE", "layer": layer, "c": (e.dxf.center.x, e.dxf.center.y), "major": (e.dxf.major_axis.x, e.dxf.major_axis.y),
                    "ratio": e.dxf.ratio, "a0": e.dxf.start_param, "a1": e.dxf.end_param}
        if t == "TEXT":
            return {"t": "TEXT", "layer": layer, "text": clean_text(e.dxf.text), "pos": (e.dxf.insert.x, e.dxf.insert.y), "h": e.dxf.height,
                    "rot": math.radians(e.dxf.rotation) if e.dxf.hasattr("rotation") else 0.0, "mtext": False}
        if t == "MTEXT":
            return {"t": "TEXT", "layer": layer, "text": clean_mtext(e.text), "pos": (e.dxf.insert.x, e.dxf.insert.y), "h": e.dxf.char_height,
                    "rot": math.radians(e.dxf.rotation) if e.dxf.hasattr("rotation") else 0.0, "mtext": True}
        if t == "HATCH":
            paths = []
            for p in e.paths:
                if p.PATH_TYPE == "PolylinePath":
                    pts = [(v[0], v[1], v[2] if len(v) > 2 else 0.0) for v in p.vertices]
                    paths.append(bulge_points(pts, True))
                else:
                    parts: list[list[tuple[float, float]]] = []
                    for ed in p.edges:
                        et = ed.EDGE_TYPE
                        if et == "LineEdge":
                            ep = [(ed.start[0], ed.start[1]), (ed.end[0], ed.end[1])]
                        elif et == "ArcEdge":
                            a0, a1 = math.radians(ed.start_angle), math.radians(ed.end_angle)
                            if not ed.ccw:
                                a0, a1 = 2 * math.pi - a0, 2 * math.pi - a1
                                if a1 > a0:
                                    a1 -= 2 * math.pi
                            elif a1 < a0:
                                a1 += 2 * math.pi
                            ep = [(ed.center[0] + ed.radius * math.cos(a0 + (a1 - a0) * i / 24), ed.center[1] + ed.radius * math.sin(a0 + (a1 - a0) * i / 24)) for i in range(25)]
                        elif et == "EllipseEdge":
                            ep = [(v.x, v.y) for v in ed.construction_tool().flattening(0.01)] if hasattr(ed, "construction_tool") else []
                        elif et == "SplineEdge":
                            ep = [(v[0], v[1]) for v in (ed.fit_points or ed.control_points)]
                        else:
                            ep = []
                        parts.append(ep)
                    pl = _chain(parts)
                    if len(pl) >= 3:
                        paths.append(pl)
            return {"t": "HATCH", "layer": layer, "paths": paths, "solid": bool(e.dxf.solid_fill), "pattern": e.dxf.pattern_name}
        if t == "INSERT":
            ins = {"t": "INSERT", "layer": layer, "name": e.dxf.name, "pos": (e.dxf.insert.x, e.dxf.insert.y), "sx": e.dxf.get("xscale", 1.0),
                   "sy": e.dxf.get("yscale", 1.0), "rot": math.radians(e.dxf.get("rotation", 0.0)), "cols": e.dxf.get("column_count", 1),
                   "rows": e.dxf.get("row_count", 1), "dx": e.dxf.get("column_spacing", 0.0), "dy": e.dxf.get("row_spacing", 0.0), "attribs": []}
            for a in e.attribs:
                ins["attribs"].append({"tag": a.dxf.tag, "text": a.dxf.text, "pos": (a.dxf.insert.x, a.dxf.insert.y)})
            return ins
        if t == "DIMENSION":
            dt = e.dimtype & 7
            d = e.dxf
            p1 = d.get("defpoint2", None)
            p2 = d.get("defpoint3", None)
            try:
                meas = float(e.get_measurement()) if hasattr(e, "get_measurement") else float(d.get("actual_measurement", 0) or 0)
            except Exception:
                meas = float(d.get("actual_measurement", 0) or 0)
            if hasattr(meas, "magnitude"):
                meas = meas.magnitude
            return {"t": "DIM", "layer": layer, "p1": (p1.x, p1.y) if p1 is not None else (0.0, 0.0), "p2": (p2.x, p2.y) if p2 is not None else (0.0, 0.0),
                    "defpt": (d.defpoint.x, d.defpoint.y), "textpos": (d.text_midpoint.x, d.text_midpoint.y) if d.hasattr("text_midpoint") else (0.0, 0.0),
                    "measurement": meas, "text": clean_mtext(d.get("text", "") or "").replace("<>", ""), "dtype": dt,
                    "rot": math.radians(d.get("angle", 0.0) or 0.0), "block": d.get("geometry")}
        if t == "SOLID" or t == "TRACE":
            return {"t": "SOLID", "layer": layer, "pts": [(v.x, v.y) for v in e.vertices()]}
        if t == "SPLINE":
            pts = e.fit_points or e.control_points
            return {"t": "SPLINE", "layer": layer, "pts": [(p[0], p[1]) for p in pts]}
        if t == "LEADER":
            return {"t": "LEADER", "layer": layer, "pts": [(p[0], p[1]) for p in e.vertices]}
        if t == "3DFACE":
            return {"t": "3DFACE", "layer": layer, "pts3": [list(map(float, v[:3])) for v in e.wcs_vertices()]}
        if t == "POINT":
            return {"t": "POINT", "layer": layer, "pos": (e.dxf.location.x, e.dxf.location.y)}
    except Exception:
        return {"t": "OTHER", "layer": layer, "type": t}
    return {"t": "OTHER", "layer": layer, "type": t}


def load_dxf(path: str | os.PathLike) -> RawDrawing:
    import ezdxf

    try:
        doc = ezdxf.readfile(str(path))
    except Exception:
        from ezdxf import recover

        doc, _auditor = recover.readfile(str(path))
    msp = doc.modelspace()
    counts: dict[str, int] = {}
    ents: list[dict] = []
    for e in msp:
        counts[e.dxftype()] = counts.get(e.dxftype(), 0) + 1
        n = _norm_dxf_entity(e)
        if n is not None:
            ents.append(n)
    blocks: dict[str, list[dict]] = {}
    base: dict[str, tuple[float, float]] = {}
    total = len(ents)
    for b in doc.blocks:
        if b.name.startswith("*Model_Space") or b.name.lower().startswith("*paper_space"):
            continue
        lst = [n for n in (_norm_dxf_entity(e) for e in b) if n is not None]
        blocks[b.name] = lst
        base[b.name] = (b.block.dxf.base_point.x, b.block.dxf.base_point.y)
        total += len(lst)
    h = doc.header
    header: dict[str, Any] = {}
    for k in ("$INSUNITS", "$MEASUREMENT", "$LUNITS", "$DIMSCALE", "$DIMLFAC"):
        if k in h:
            header[k[1:]] = h[k]
    for k in ("$EXTMIN", "$EXTMAX"):
        if k in h:
            header[k[1:]] = [float(h[k][0]), float(h[k][1]), float(h[k][2])]
    layers = [{"name": l.dxf.name, "color": l.dxf.color, "frozen": l.is_frozen(), "off": l.is_off()} for l in doc.layers]
    rd = RawDrawing(kind="dxf", file=os.path.basename(str(path)), version=doc.dxfversion, header=header, layers=layers, blocks=blocks,
                    block_base=base, entities=ents, raw_type_counts=counts)
    rd.total_entity_count = total
    return rd


def load_drawing(path: str | os.PathLike, cache_dir: Path | None = None) -> RawDrawing:
    ext = os.path.splitext(str(path))[1].lower()
    if ext == ".dwg":
        return load_dwg(path, cache_dir)
    if ext == ".dxf":
        return load_dxf(path)
    raise ValueError(f"unsupported drawing type: {ext}")
