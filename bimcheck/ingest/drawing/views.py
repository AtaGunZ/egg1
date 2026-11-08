"""Segmentation of model space into views (sheet frames / spatial clusters) and classification from titles."""
from __future__ import annotations

import math
import re
from typing import Any

import numpy as np
from shapely import STRtree, box

from . import vocab
from .scene import Scene


def _is_rect(e: dict, tol_frac: float = 0.002) -> tuple[float, float, float, float] | None:
    if e["t"] != "POLY" or not e["closed"]:
        return None
    pts = e["pts"]
    if len(pts) == 5 and math.hypot(pts[0][0] - pts[-1][0], pts[0][1] - pts[-1][1]) < 1e-6:
        pts = pts[:4]
    if len(pts) != 4 or any(abs(p[2]) > 1e-9 for p in pts):
        return None
    xs = [p[0] for p in pts]
    ys = [p[1] for p in pts]
    w, h = max(xs) - min(xs), max(ys) - min(ys)
    if w <= 0 or h <= 0:
        return None
    tol = tol_frac * max(w, h)
    for i in range(4):
        a, b = pts[i], pts[(i + 1) % 4]
        if abs(a[0] - b[0]) > tol and abs(a[1] - b[1]) > tol:
            return None
    return (min(xs), min(ys), max(xs), max(ys))


def detect_frames(scene: Scene) -> list[dict]:
    """Detect sheet frames: large axis-aligned rectangles, preferably double-bordered (nested twin within ~1% size)."""
    x0, y0, x1, y1 = scene.extents
    ext = max(x1 - x0, y1 - y0, 1e-9)
    cands = []
    for e in scene.ents:
        if e.get("blk"):
            continue
        r = _is_rect(e)
        if r is None:
            continue
        w, h = r[2] - r[0], r[3] - r[1]
        if min(w, h) >= 0.02 * ext:
            cands.append({"bb": r, "layer": e["layer"], "ent": e})
    if not cands:
        return []
    # pair with nested twins
    frames = []
    used = set()
    for i, a in enumerate(cands):
        if i in used:
            continue
        wa, ha = a["bb"][2] - a["bb"][0], a["bb"][3] - a["bb"][1]
        tol = 0.012 * max(wa, ha)
        twin = None
        for j, b in enumerate(cands):
            if j == i or j in used:
                continue
            wb, hb = b["bb"][2] - b["bb"][0], b["bb"][3] - b["bb"][1]
            if abs(wa - wb) < 2 * tol and abs(ha - hb) < 2 * tol and all(abs(a["bb"][k] - b["bb"][k]) < 2 * tol for k in range(4)) and (wa != wb or ha != hb):
                twin = j
                break
        if twin is not None:
            b = cands[twin]
            used.add(i)
            used.add(twin)
            outer = (min(a["bb"][0], b["bb"][0]), min(a["bb"][1], b["bb"][1]), max(a["bb"][2], b["bb"][2]), max(a["bb"][3], b["bb"][3]))
            frames.append({"bb": outer, "kind": "double", "layer": a["layer"]})
    if frames:
        frames.sort(key=lambda f: (f["bb"][0], f["bb"][1]))
        # a frame fully containing another one is a sheet-of-sheets (drop the container)
        keep = []
        for f in frames:
            inside = [g for g in frames if g is not f and g["bb"][0] >= f["bb"][0] - 1 and g["bb"][1] >= f["bb"][1] - 1 and g["bb"][2] <= f["bb"][2] + 1 and g["bb"][3] <= f["bb"][3] + 1]
            if not inside:
                keep.append(f)
        return keep
    # single-border frames: only accept if they are large relative to the drawing and few
    big = [c for c in cands if (c["bb"][2] - c["bb"][0]) >= 0.2 * ext or (c["bb"][3] - c["bb"][1]) >= 0.2 * ext]
    return [{"bb": c["bb"], "kind": "single", "layer": c["layer"]} for c in big] if 0 < len(big) <= 40 else []


def cluster_boxes(boxes: np.ndarray, gap: float) -> np.ndarray:
    """Union-find clustering of boxes whose (gap-expanded) rectangles overlap. Returns label array."""
    n = len(boxes)
    parent = list(range(n))

    def find(a: int) -> int:
        while parent[a] != a:
            parent[a] = parent[parent[a]]
            a = parent[a]
        return a

    geoms = [box(b[0] - gap / 2, b[1] - gap / 2, b[2] + gap / 2, b[3] + gap / 2) for b in boxes]
    tree = STRtree(geoms)
    left, right = tree.query(geoms, predicate="intersects")
    for a, b in zip(left, right):
        if a != b:
            ra, rb = find(int(a)), find(int(b))
            if ra != rb:
                parent[ra] = rb
    return np.array([find(i) for i in range(n)])


def _text_items(scene: Scene, bb) -> list[dict]:
    return [t for t in scene.texts if bb[0] <= t["pos"][0] <= bb[2] and bb[1] <= t["pos"][1] <= bb[3]]


SCALE_RE = re.compile(r"(?:OLCEK|OLCE[GK]I?|SCALE|O)\s*[:=]?\s*1\s*[/:]\s*(\d+)", re.I)


def scale_denominator(text: str) -> int | None:
    f = vocab.fold(text)
    m = re.search(r"(?:OLCEK|SCALE)\s*[:=]?\s*1\s*[/:]\s*(\d+)", f)
    if m:
        return int(m.group(1))
    m = re.search(r"\bO\s*:\s*1\s*/\s*(\d+)", f)
    if m:
        return int(m.group(1))
    m = re.search(r",\s*1/(\d+)\s*$", f)
    if m:
        return int(m.group(1))
    return None


def _title_in_frame(scene: Scene, bb) -> tuple[dict | None, int | None]:
    """Pick the sheet title text inside a frame (bottom 20% preferred) and the nearest scale text."""
    h = bb[3] - bb[1]
    texts = _text_items(scene, bb)
    cands = []
    for t in texts:
        s = t["text"].strip()
        if not s or len(s) > 60:
            continue
        kind = vocab.view_kind_from_title(s)
        if kind is None:
            continue
        if "OLCEK" in vocab.fold(s) and "PLAN" not in vocab.fold(s):
            continue
        depth = (t["pos"][1] - bb[1]) / h  # 0 = bottom
        score = (t["h"] or 1.0) * (20.0 if depth < 0.08 else 1.0)
        cands.append((score, t, kind))
    if not cands:
        return None, None
    cands.sort(key=lambda c: -c[0])
    title = cands[0][1]
    den = None
    for t in texts:
        d = scale_denominator(t["text"])
        if d and abs(t["pos"][0] - title["pos"][0]) < 0.3 * (bb[2] - bb[0]) and abs(t["pos"][1] - title["pos"][1]) < 0.06 * h:
            den = d
            break
    return title, den


def build_views(scene: Scene, warnings: list[str]) -> list[dict]:
    """Return view dicts: {id,kind,name,level_hint,bbox_raw,frame(bool),parent,scale_denominator,title_pos,source}."""
    frames = detect_frames(scene)
    views: list[dict] = []
    if frames:
        for fr in frames:
            bb = fr["bb"]
            title, den = _title_in_frame(scene, bb)
            kind = vocab.view_kind_from_title(title["text"]) if title else None
            name = title["text"].strip() if title else None
            views.append({"kind": kind or "unknown", "name": name, "level_hint": vocab.level_hint_from_title(name) if name else None,
                          "bbox_raw": list(bb), "frame": True, "parent": None, "scale_denominator": den, "title_pos": title["pos"] if title else None,
                          "source": "frame"})
        views.sort(key=lambda v: (v["bbox_raw"][0], v["bbox_raw"][1]))
        views = _add_subviews(scene, views)
    else:
        views = _cluster_views(scene, warnings)
    for i, v in enumerate(views, 1):
        v["id"] = f"v{i}"
    for v in views:
        if v.get("_parent_idx") is not None:
            v["parent"] = views[v.pop("_parent_idx")]["id"]
    return views


def _add_subviews(scene: Scene, views: list[dict]) -> list[dict]:
    """Split section/elevation sheets that carry several titled drawings ("A-A KESİTİ", "GÜNEY GÖRÜNÜŞÜ" ...) into column bands."""
    out: list[dict] = []
    for v in views:
        out.append(v)
        if v["kind"] not in ("section", "elevation"):
            continue
        bb = v["bbox_raw"]
        h = bb[3] - bb[1]
        anchors = []
        for t in _text_items(scene, bb):
            s = t["text"].strip()
            f = vocab.fold(s)
            if len(s) > 50 or not re.search(r"KESIT|GORUNUS|CEPHE|ELEVATION|SECTION", f) or "OLCEK" in f or "BOYA" in f or "DETAY" in f:
                continue
            if t["h"] and t["h"] < 0.004 * h:
                continue
            kind = vocab.view_kind_from_title(s)
            if kind in ("section", "elevation"):
                anchors.append((t, kind))
        # remove duplicates / the sheet title itself
        anchors = [(t, k) for t, k in anchors if v["title_pos"] is None or math.dist(t["pos"], v["title_pos"]) > 1.0]
        if len(anchors) < 2:
            continue
        anchors.sort(key=lambda a: a[0]["pos"][0])
        # cluster anchors by x (titles in a row)
        xs = [a[0]["pos"][0] for a in anchors]
        bounds = [bb[0]] + [(xs[i] + xs[i + 1]) / 2 for i in range(len(xs) - 1)] + [bb[2]]
        pidx = len(out) - 1
        for (t, k), x0, x1 in zip(anchors, bounds[:-1], bounds[1:]):
            den = None
            for t2 in scene.texts:
                d = scale_denominator(t2["text"])
                if d and abs(t2["pos"][0] - t["pos"][0]) < 0.05 * (bb[2] - bb[0]) and 0 < t["pos"][1] - t2["pos"][1] < 0.03 * h + (t["h"] or 0) * 3:
                    den = d
                    break
            out.append({"kind": k, "name": t["text"].strip(), "level_hint": None, "bbox_raw": [x0, bb[1], x1, bb[3]], "frame": False, "parent": None,
                        "_parent_idx": pidx, "scale_denominator": den, "title_pos": t["pos"], "source": "subtitle-band"})
        v["has_subviews"] = True
    return out


def _cluster_views(scene: Scene, warnings: list[str]) -> list[dict]:
    """No sheet frames: gap-cluster all entities; classify clusters from nearby titles."""
    x0, y0, x1, y1 = scene.extents
    ext = max(x1 - x0, y1 - y0, 1e-9)
    gap = 0.03 * ext
    idx = [i for i, e in enumerate(scene.ents) if np.isfinite(scene.bboxes[i]).all() and e["t"] not in ("OTHER",)]
    if not idx:
        return []
    boxes = scene.bboxes[idx]
    labels = cluster_boxes(boxes, gap)
    clusters: dict[int, list[int]] = {}
    for lab, i in zip(labels, idx):
        clusters.setdefault(int(lab), []).append(i)
    views = []
    for lab, members in clusters.items():
        if len(members) < 5:
            continue
        b = scene.bboxes[members]
        bb = [float(b[:, 0].min()), float(b[:, 1].min()), float(b[:, 2].max()), float(b[:, 3].max())]
        views.append({"kind": "unknown", "name": None, "level_hint": None, "bbox_raw": bb, "frame": False, "parent": None, "scale_denominator": None,
                      "title_pos": None, "source": "gap-cluster", "n": len(members)})
    # titles
    for v in views:
        bb = v["bbox_raw"]
        pad = 0.1 * max(bb[2] - bb[0], bb[3] - bb[1])
        best = None
        for t in scene.texts:
            if bb[0] - pad <= t["pos"][0] <= bb[2] + pad and bb[1] - pad <= t["pos"][1] <= bb[3] + pad:
                k = vocab.view_kind_from_title(t["text"])
                if k and len(t["text"]) < 60 and (best is None or (t["h"] or 0) > (best[0]["h"] or 0)):
                    best = (t, k)
        if best:
            v["kind"] = best[1]
            v["name"] = best[0]["text"].strip()
            v["level_hint"] = vocab.level_hint_from_title(v["name"])
            v["title_pos"] = best[0]["pos"]
    views.sort(key=lambda v: (-(v["bbox_raw"][2] - v["bbox_raw"][0]) * (v["bbox_raw"][3] - v["bbox_raw"][1])))
    return views[:30]


def assign_views(scene: Scene, views: list[dict]) -> None:
    """Set e['view'] (smallest containing view by bbox centre) for entities and texts; None if outside every view."""
    order = sorted(range(len(views)), key=lambda i: (views[i]["bbox_raw"][2] - views[i]["bbox_raw"][0]) * (views[i]["bbox_raw"][3] - views[i]["bbox_raw"][1]))
    vb = np.array([views[i]["bbox_raw"] for i in order]) if views else np.zeros((0, 4))
    ids = [views[i]["id"] for i in order]

    def which(cx: float, cy: float) -> str | None:
        if not len(vb):
            return None
        m = (vb[:, 0] <= cx) & (cx <= vb[:, 2]) & (vb[:, 1] <= cy) & (cy <= vb[:, 3])
        w = np.nonzero(m)[0]
        return ids[w[0]] if len(w) else None

    for e, b in zip(scene.ents, scene.bboxes):
        if not np.isfinite(b).all():
            e["view"] = None
            continue
        e["view"] = which((b[0] + b[2]) / 2, (b[1] + b[3]) / 2)
    for t in scene.texts:
        t["view"] = which(t["pos"][0], t["pos"][1])
    for e in scene.inserts:
        e["view"] = which(e["pos"][0], e["pos"][1])
