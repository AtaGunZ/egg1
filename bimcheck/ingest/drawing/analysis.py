"""Analysis steps: layer roles, units, per-view scale, parcel, footprint, rooms, openings, stairs, annotations."""
from __future__ import annotations

import math
import re
import statistics
from collections import Counter, defaultdict
from typing import Any

import numpy as np
from shapely.geometry import LineString, MultiPoint, Point, Polygon
from shapely.ops import polygonize, unary_union
from shapely import make_valid

from . import geom, vocab
from .reader import bulge_points
from .scene import Scene

NICE = [0.1, 0.2, 0.25, 0.5, 1, 2, 2.5, 4, 5, 10, 20, 25, 40, 50, 100]


# ------------------------------------------------------------------------------------------------ layer roles
def _is_room_word(s: str) -> bool:
    return bool(vocab.ROOM_WORDS.search(vocab.fold(s)))


def layer_roles(scene: Scene, overrides: dict[str, str] | None, warnings: list[str]) -> list[dict]:
    stats: dict[str, Counter] = defaultdict(Counter)
    for e in scene.ents:
        if e.get("blk"):
            continue
        stats[e["layer"]][e["t"]] += 1
        if e["t"] == "POLY" and e["closed"]:
            stats[e["layer"]]["closed"] += 1
    texts_by: dict[str, list[str]] = defaultdict(list)
    for t in scene.texts:
        if not t.get("blk") and not t.get("from_attrib"):
            texts_by[t["layer"]].append(t["text"])
            stats[t["layer"]]["TEXT"] += 1
    for i in scene.inserts:
        stats[i["layer"]]["INSERT"] += 1
    out = []
    names = list(scene.layer_names)
    for n in stats:
        if n not in names:
            names.append(n)
    for name in names:
        st = stats.get(name, Counter())
        total = sum(v for k, v in st.items() if k not in ("closed",))
        role, conf = vocab.role_from_name(name)
        source = "name"
        notes = []
        tx = texts_by.get(name, [])
        n_text = len(tx)
        # content statistics for text-bearing layers
        if n_text >= 5:
            area_share = sum(vocab.parse_area_text(s) is not None for s in tx) / n_text
            room_share = sum(_is_room_word(s) for s in tx) / n_text
            if role == "room_label" and room_share < 0.15:
                notes.append(f"name suggests room labels but only {room_share:.0%} of texts look like room names")
                role, conf, source = "text", 0.4, "geometry"
            elif role in ("unknown", "text") and area_share > 0.5:
                role, conf, source = "area_label", min(0.5 + area_share / 2, 0.9), "geometry"
            elif role in ("unknown", "text") and room_share > 0.4:
                role, conf, source = "room_label", min(0.4 + room_share / 2, 0.9), "geometry"
        if role in ("room_label", "area_label", "text") and total and st.get("TEXT", 0) / total < 0.2 and role != "text":
            notes.append(f"name suggests '{role}' but layer holds {st.get('TEXT', 0)} texts of {total} entities")
            conf = min(conf, 0.3)
        if role == "unknown" and total:
            if st.get("TEXT", 0) / total > 0.6:
                role, conf, source = "text", 0.5, "geometry"
            elif st.get("DIM", 0) / total > 0.5:
                role, conf, source = "dimension", 0.8, "geometry"
            elif st.get("HATCH", 0) / total > 0.6:
                role, conf, source = "hatch", 0.5, "geometry"
            elif (st.get("LINE", 0) + st.get("POLY", 0)) / total > 0.7:
                role, conf, source = "unknown", 0.1, "geometry"
        if role == "dimension" and total and st.get("DIM", 0) == 0 and st.get("TEXT", 0) == 0:
            conf = min(conf, 0.5)
        if overrides and name in overrides:
            role, conf, source = overrides[name], 1.0, "user"
        out.append({"name": name, "entity_count": int(total), "role": role, "role_confidence": round(conf, 2), "role_source": source,
                    **({"extra": {"notes": notes}} if notes else {})})
    return out


# ------------------------------------------------------------------------------------------------ units
INSUNITS = {1: ("unknown", 0.0254), 2: ("unknown", 0.3048), 4: ("mm", 0.001), 5: ("cm", 0.01), 6: ("m", 1.0), 3: ("unknown", 1609.344),
            7: ("unknown", 1000.0), 8: ("unknown", 2.54e-8), 9: ("unknown", 2.54e-5), 10: ("unknown", 0.9144), 14: ("unknown", 0.1), 15: ("unknown", 10.0)}


def _dim_ratio(e: dict) -> tuple[float, float] | None:
    """(ratio measurement/geometry, measurement) for a linear/aligned dimension, ratio snapped to a nice number."""
    if e["dtype"] not in (0, 1) or e["measurement"] <= 0:
        return None
    dx, dy = abs(e["p1"][0] - e["p2"][0]), abs(e["p1"][1] - e["p2"][1])
    cands = [math.hypot(dx, dy), dx, dy]
    for c in cands:
        if c > 1e-6:
            r = e["measurement"] / c
            for n in NICE:
                if abs(r - n) / n < 0.015:
                    return (n, e["measurement"])
    return None


def detect_units(scene: Scene, warnings: list[str]) -> dict:
    hdr = scene.raw.header.get("INSUNITS")
    hdr_unit = INSUNITS.get(hdr) if hdr else None
    ms = [m for r in (_dim_ratio(e) for e in scene.ents if e["t"] == "DIM") if r for m in [r[1]]]
    evidence: dict[str, Any] = {"header_insunits": hdr, "n_dimensions": len(ms)}
    x0, y0, x1, y1 = scene.extents
    ext = max(x1 - x0, y1 - y0)
    evidence["extent_drawing_units"] = round(ext, 2)
    unit, scale, source = "unknown", None, "assumed"
    if len(ms) >= 10:
        med = statistics.median(ms)
        evidence["median_dimension_value"] = med
        for u, s in (("m", 1.0), ("cm", 0.01), ("mm", 0.001)):
            if 0.8 <= med * s <= 12:
                unit, scale = u, s
                break
        if scale is not None:
            source = "dimension-ratio"
            if hdr_unit and hdr_unit[1] == scale:
                source = "header"
            elif hdr_unit:
                warnings.append(f"header $INSUNITS={hdr} ({hdr_unit[0]}) contradicts dimension values (median {med:g} => {unit}); using {unit}")
    if scale is None and hdr_unit:
        unit, scale = hdr_unit
        source = "header"
        # plausibility of the extent: a single building/site is rarely > 3 km or < 3 m
        if ext * scale > 5000 or ext * scale < 3:
            warnings.append(f"header unit {unit} gives implausible drawing extent {ext * scale:.1f} m")
    if scale is None:
        unit, scale, source = "unknown", 0.01 if ext > 500 else 1.0, "assumed"
        warnings.append(f"no unit information; assumed scale {scale} m/unit")
    return {"units": unit, "unit_scale_to_m": scale, "unit_source": source, "evidence": evidence}


def view_scales(scene: Scene, views: list[dict], warnings: list[str]) -> None:
    """Set v['scale_factor'] = drawn-length -> real-length multiplier (1/200 sheets drawn at 1/4 size => 4)."""
    per: dict[str, list[float]] = defaultdict(list)
    for e in scene.ents:
        if e["t"] == "DIM" and e.get("view"):
            r = _dim_ratio(e)
            if r:
                per[e["view"]].append(r[0])
    dens = [v["scale_denominator"] for v in views if v.get("scale_denominator") and v["kind"] == "floor_plan"]
    base = statistics.mode(dens) if dens else None
    for v in views:
        rs = per.get(v["id"], [])
        if len(rs) >= 5:
            c = Counter(rs)
            f, n = c.most_common(1)[0]
            v["scale_factor"], v["scale_source"] = float(f), f"dimension-ratio({n}/{len(rs)})"
        elif v.get("scale_denominator") and base:
            v["scale_factor"], v["scale_source"] = v["scale_denominator"] / base, "title-scale"
        else:
            p = next((w for w in views if w["id"] == v.get("parent")), None)
            if p and "scale_factor" in p:
                v["scale_factor"], v["scale_source"] = p["scale_factor"], "parent"
            else:
                v["scale_factor"], v["scale_source"] = 1.0, "assumed"


# ------------------------------------------------------------------------------------------------ helpers
def _lines_of(ents: list[dict], types=("LINE", "POLY", "ARC")) -> list[LineString]:
    out = []
    for e in ents:
        if e["t"] not in types:
            continue
        for pts, closed in geom.entity_lines(e):
            p = list(pts)
            if closed and p and p[0] != p[-1]:
                p.append(p[0])
            if len(p) >= 2:
                out.append(LineString(p))
    return out


def _clean(poly):
    if poly is None or poly.is_empty:
        return None
    if not poly.is_valid:
        poly = make_valid(poly)
    if poly.geom_type == "MultiPolygon":
        poly = max(poly.geoms, key=lambda g: g.area)
    return poly if poly.geom_type == "Polygon" else None


def _metric(pts, f: float):
    return [[round(x * f, 4), round(y * f, 4)] for x, y in pts]


# ------------------------------------------------------------------------------------------------ parcel
def extract_parcel(scene: Scene, views: list[dict], roles: dict[str, str], unit_scale: float, warnings: list[str]) -> dict | None:
    parcel_layers = {n for n, r in roles.items() if r == "parcel"}
    if not parcel_layers:
        warnings.append("parcel: no layer with role 'parcel'")
        return None
    best = None
    for v in views:
        if v["kind"] != "site_plan":
            continue
        ents = [e for e in scene.ents if e.get("view") == v["id"] and e["layer"] in parcel_layers and not e.get("blk")]
        # drop section-marker lines: a one/two-letter text on the same layer near an endpoint
        marks = [t["pos"] for t in scene.texts if t["layer"] in parcel_layers and len(t["text"].strip()) <= 2 and t.get("view") == v["id"]]
        lines = []
        for e in ents:
            if e["t"] not in ("LINE", "POLY"):
                continue
            if e["t"] == "LINE":
                L = math.dist(e["p1"], e["p2"])
                if L < 1e-6:
                    continue
                if any(math.dist(m, e["p1"]) < 0.08 * L + 30 or math.dist(m, e["p2"]) < 0.08 * L + 30 for m in marks):
                    continue
            lines += _lines_of([e])
        if len(lines) < 3:
            continue
        ext = []
        from shapely import affinity
        for ln in lines:
            if ln.length < 0.02 * max(v["bbox_raw"][2] - v["bbox_raw"][0], 1):
                continue
            (xa, ya), (xb, yb) = ln.coords[0], ln.coords[-1]
            k = 0.12
            if len(ln.coords) == 2:
                ext.append(LineString([(xa - (xb - xa) * k, ya - (yb - ya) * k), (xb + (xb - xa) * k, yb + (yb - ya) * k)]))
            else:
                ext.append(ln)
        polys = [p for p in polygonize(unary_union(ext)) if p.area > 0]
        if not polys:
            continue
        polys.sort(key=lambda p: -p.area)
        cand = polys[0]
        f = unit_scale * v.get("scale_factor", 1.0)
        # labelled area text in the same view: "PARSEL ALANI:836,35m²"
        lab = None
        for t in scene.texts:
            if t.get("view") == v["id"] and re.search(r"PARSEL ALAN|ARSA ALAN", vocab.fold(t["text"])):
                lab = vocab.parse_area_text(t["text"]) or vocab.parse_number(t["text"].split(":")[-1])
        score = len(lines)
        if best is None or score > best[0]:
            best = (score, v, cand, polys, f, lab, len(lines))
    if best is None:
        warnings.append("parcel: no closed boundary could be reconstructed from parcel-layer linework")
        return None
    _, v, cand, polys, f, lab, nl = best
    cand = _clean(cand.simplify(0.0))
    pts = list(cand.exterior.coords)[:-1]
    if not cand.exterior.is_ccw:
        pts = pts[::-1]
    # simplify collinear
    poly_m = Polygon(_metric(pts, f))
    area = poly_m.area
    out = {"polygon": _metric(pts, f), "area": round(area, 2), "layer": "/".join(sorted({n for n in roles if roles[n] == "parcel"})), "view_id": v["id"],
           "source": "polyline", "extra": {"labelled_area": lab, "reconstructed_from_lines": nl, "method": "extended-line polygonize",
                                           "edge_lengths_m": [round(math.dist(pts[i], pts[(i + 1) % len(pts)]) * f, 2) for i in range(len(pts))],
                                           "setback_polygon": None, "coordinate_frame": "view metric frame (drawing coords x unit_scale x view scale_factor)"}}
    if len(polys) > 1:
        inner = polys[1]
        if cand.contains(inner.representative_point()) and inner.area > 0.2 * cand.area:
            ip = list(inner.exterior.coords)[:-1]
            out["extra"]["setback_polygon"] = {"polygon": _metric(ip, f), "area": round(inner.area * f * f, 2)}
    if lab and abs(lab - area) / lab > 0.03:
        warnings.append(f"parcel: computed area {area:.2f} m2 differs from labelled {lab:.2f} m2 by {(area - lab) / lab:+.1%}")
    if lab is None:
        warnings.append("parcel: no labelled area text found for cross-check")
    out["extra"]["confidence"] = 0.8 if lab and abs(lab - area) / lab <= 0.03 else 0.5
    return out


# ------------------------------------------------------------------------------------------------ footprint
def _wall_lines(scene: Scene, view_id: str, roles: dict[str, str], include=("wall", "column")) -> list[LineString]:
    ents = [e for e in scene.ents if e.get("view") == view_id and roles.get(e["layer"]) in include and e["t"] in ("LINE", "POLY") and not e.get("blk")]
    return _lines_of(ents)


def _boundary_names(roles, glazing=False):
    base = {n for n, r in roles.items() if r in ("wall", "column")} | {n for n in roles if re.search(r"SIVA", vocab.fold(n))}
    if glazing:
        base |= {n for n, r in roles.items() if r in ("window", "door")} | {n for n in roles if re.search(r"SABITEL|CERCEVE", vocab.fold(n))}
    return base


def _envelope(scene: Scene, view: dict, roles: dict[str, str], f: float, close_m: float, glazing: bool = False, clip=None):
    names = _boundary_names(roles, glazing)
    vw = view["bbox_raw"][2] - view["bbox_raw"][0]
    ents = [e for e in scene.ents if e.get("view") == view["id"] and e["layer"] in names and e["t"] in ("LINE", "POLY") and not e.get("blk")]
    lines = [l for l in _lines_of(ents) if 0.1 / f < l.length < 0.5 * vw]
    if clip is not None:
        lines = [l for l in lines if clip.contains(l)]
    if len(lines) < 10:
        return None, lines
    u = unary_union([l.buffer(close_m / f, join_style=2) for l in lines])
    comps = list(u.geoms) if u.geom_type == "MultiPolygon" else [u]
    comps.sort(key=lambda g: -g.area)
    main = comps[0]
    # keep components that are big enough to be part of the building (>= 8% of the main one)
    parts = [Polygon(c.exterior) for c in comps if c.area >= 0.08 * main.area]
    env = unary_union(parts)
    env = Polygon(max(env.geoms, key=lambda g: g.area).exterior) if env.geom_type == "MultiPolygon" else Polygon(env.exterior)
    env = env.buffer(-close_m / f * 0.95, join_style=2)
    env = env.buffer(-1.5 / f, join_style=2).buffer(1.5 / f, join_style=2)  # drop thin spikes (section marks, leaders)
    if env.geom_type == "MultiPolygon":
        env = max(env.geoms, key=lambda g: g.area)
    return env, lines


def extract_footprint(scene: Scene, view: dict, roles: dict[str, str], f: float, warnings: list[str], glazing: bool = False, clip=None) -> dict | None:
    env, lines = _envelope(scene, view, roles, f, 1.0, glazing, clip)
    if env is None:
        warnings.append(f"footprint: too little wall linework in view {view['id']}")
        return None
    solid = _clean(env.simplify(0.05 / f))
    if solid is None:
        return None
    pts = list(solid.exterior.coords)[:-1]
    if not solid.exterior.is_ccw:
        pts = pts[::-1]
    area = Polygon(_metric(pts, f)).area
    inside = sum(l.length for l in lines if solid.buffer(0.3 / f).contains(l)) / max(sum(l.length for l in lines), 1e-9)
    return {"polygon": _metric(pts, f), "area": round(area, 2), "view_id": view["id"], "confidence": round(min(0.75, 0.25 + 0.5 * inside), 2),
            "extra": {"method": "closing (1 m) of wall/column/plaster linework, outer ring; includes projecting balconies/columns drawn on those layers",
                      "layers": sorted(_boundary_names(roles, glazing))}}


# ------------------------------------------------------------------------------------------------ rooms
def _room_label_pairs(scene: Scene, view_id: str) -> list[dict]:
    """Pair room-name texts with the area text placed just below them ("A:12,50m²")."""
    texts = [t for t in scene.texts if t.get("view") == view_id and not t.get("blk")]
    areas = [(t, vocab.parse_area_text(t["text"])) for t in texts]
    areas = [(t, a) for t, a in areas if a is not None]
    out = []
    for t in texts:
        s = t["text"].strip()
        fs = vocab.fold(s)
        if not s or vocab.parse_area_text(s) is not None or len(s) > 26 or re.search(r"ALANI|NOT ?:|TOPLAM|YAPILACAK|PROJE|NET ALAN|MINHA|BRUT|ASP\.? ?BC|PLATFORM", fs):
            continue
        if not _is_room_word(s) and not re.search(r"\bWC\b|\bLV\b", vocab.fold(s)):
            continue
        h = t["h"] or 12
        best = None
        for a, val in areas:
            dx, dy = a["pos"][0] - t["pos"][0], t["pos"][1] - a["pos"][1]
            if -0.5 * h <= dy <= 3.2 * h and abs(dx) <= 8 * h:
                d = math.hypot(dx, dy)
                if best is None or d < best[0]:
                    best = (d, a, val)
        out.append({"name": s, "pos": t["pos"], "h": h, "area_text": best[1]["text"] if best else None, "labelled": best[2] if best else None})
    # de-duplicate identical label at identical place
    seen, res = set(), []
    for o in out:
        k = (o["name"], round(o["pos"][0]), round(o["pos"][1]))
        if k not in seen:
            seen.add(k)
            res.append(o)
    return res


def extract_rooms(scene: Scene, view: dict, roles: dict[str, str], f: float, counter: list[int], warnings: list[str]) -> list[dict]:
    labels = _room_label_pairs(scene, view["id"])
    if not labels:
        return []
    bnames = {n for n, r in roles.items() if r in ("wall", "column", "window", "door")} | {n for n in roles if re.search(r"SIVA|SABITEL|CERCEVE|DOGRAMA", vocab.fold(n))}
    vb = view["bbox_raw"]
    vw = vb[2] - vb[0]
    ents_b = [e for e in scene.ents if e.get("view") == view["id"] and e["layer"] in bnames and e["t"] in ("LINE", "POLY") and not e.get("blk")]
    lines = [l for l in _lines_of(ents_b) if 0.05 / f < l.length < 0.5 * vw]
    if len(lines) < 10:
        return []
    interior, _ = _envelope(scene, view, roles, f, 1.0)
    if interior is None:
        return []
    tol = 0.02 / f
    mask = unary_union([l.buffer(tol) for l in lines])
    free = interior.difference(mask)
    d = 0.42 / f
    core = free.buffer(-d)
    comps = [c for c in (list(core.geoms) if core.geom_type == "MultiPolygon" else [core]) if not c.is_empty]
    rooms = []
    # label -> component
    assign: dict[int, list[dict]] = defaultdict(list)
    for lb in labels:
        p = Point(lb["pos"][0] + len(lb["name"]) * lb["h"] * 0.3, lb["pos"][1] - lb["h"])
        hit = None
        for i, c in enumerate(comps):
            if c.contains(p):
                hit = i
                break
        if hit is None:
            dist = [(c.distance(p), i) for i, c in enumerate(comps)]
            if dist:
                dd, i = min(dist)
                if dd < 0.6 / f:
                    hit = i
        if hit is not None:
            assign[hit].append(lb)
        else:
            counter[0] += 1
            rooms.append({"id": f"r{counter[0]}", "view_id": view["id"], "name": lb["name"], "usage": vocab.usage_from_name(lb["name"]) or "other",
                          "polygon": None, "area": None, "labelled_area": lb["labelled"], "min_width": None, "label_point": _metric([lb["pos"]], f)[0],
                          "confidence": 0.1, "extra": {"note": "no enclosed polygon found for this label"}})
    for i, lbs in assign.items():
        c = comps[i]
        region = c.buffer(d, join_style=2).intersection(free)
        region = _clean(region) or _clean(c)
        if region is None:
            continue
        if len(lbs) > 1:
            # split among labels by nearest label point (low confidence)
            pts = [Point(l["pos"][0], l["pos"][1] - l["h"]) for l in lbs]
            parts = [[] for _ in lbs]
            from shapely.ops import voronoi_diagram
            try:
                vd = voronoi_diagram(MultiPoint(pts), envelope=region.envelope.buffer(10 / f))
                cells = [_clean(g.intersection(region)) for g in vd.geoms]
            except Exception:
                cells = [region]
            for lb in lbs:
                p = Point(lb["pos"][0], lb["pos"][1] - lb["h"])
                cell = next((g for g in cells if g is not None and g.contains(p)), None)
                if cell is None:
                    continue
                rooms.append(_mk_room(view, lb, cell, f, counter, 0.35, "shared component split by label proximity"))
        else:
            rooms.append(_mk_room(view, lbs[0], region, f, counter, 0.8, "enclosed by wall linework"))
    return rooms


def _mk_room(view, lb, poly, f, counter, conf, note):
    counter[0] += 1
    poly = poly.simplify(0.02 / f)
    pts = list(poly.exterior.coords)[:-1]
    if not poly.exterior.is_ccw:
        pts = pts[::-1]
    pm = Polygon(_metric(pts, f))
    area = pm.area
    short = geom.min_rotated_rect_dims(pm)[0] if pm.area > 0 else None
    lab = lb["labelled"]
    c = conf
    if lab:
        rel = abs(area - lab) / lab
        c = conf * (1.0 if rel < 0.1 else 0.6 if rel < 0.25 else 0.35)
    else:
        c = conf * 0.8
    r = {"id": f"r{counter[0]}", "view_id": view["id"], "name": lb["name"], "usage": vocab.usage_from_name(lb["name"]) or "other", "polygon": _metric(pts, f),
         "area": round(area, 2), "labelled_area": lab, "min_width": round(short, 2) if short else None,
         "label_point": _metric([lb["pos"]], f)[0], "confidence": round(c, 2), "extra": {"note": note}}
    if lab and abs(area - lab) / lab > 0.1:
        r["extra"]["area_mismatch"] = f"computed {area:.2f} vs labelled {lab:.2f}"
    return r
