"""Drawing ingest (S3): DWG/DXF -> DrawingModel (see docs/CONTRACTS.md section 2)."""
from __future__ import annotations

import math
import os
import re
from typing import Any

from . import analysis, geom, vocab, views as views_mod
from .reader import load_drawing
from .scene import build_scene

__all__ = ["extract_drawing_model"]


def _mm(p, f):
    return [round(p[0] * f, 4), round(p[1] * f, 4)]


def extract_drawing_model(path: str, *, layer_roles: dict[str, str] | None = None, cache_dir=None, _debug: dict | None = None) -> dict:
    warnings: list[str] = []
    raw = load_drawing(path, cache_dir)
    scene = build_scene(raw)
    views = views_mod.build_views(scene, warnings)
    views_mod.assign_views(scene, views)
    layers = analysis.layer_roles(scene, layer_roles, warnings)
    roles = {l["name"]: l["role"] for l in layers}
    units = analysis.detect_units(scene, warnings)
    analysis.view_scales(scene, views, warnings)
    us = units["unit_scale_to_m"]
    vf = {v["id"]: us * v["scale_factor"] for v in views}

    if not views:
        warnings.append("no views could be segmented")
    if units["unit_source"] != "header":
        pass

    parcel = analysis.extract_parcel(scene, views, roles, us, warnings)

    plans = [v for v in views if v["kind"] == "floor_plan" and v.get("name") and v["level_hint"] is not None]
    ground = next((v for v in plans if v["level_hint"] == 0), None)
    footprint = None
    if ground is not None:
        footprint = analysis.extract_footprint(scene, ground, roles, vf[ground["id"]], warnings, glazing=True)
        others = [v for v in plans if v["level_hint"] and v["level_hint"] > 0]
        ref = None
        for ov in others[:1]:
            ref = analysis.extract_footprint(scene, ov, roles, vf[ov["id"]], warnings)
        if ref and (footprint is None or footprint["area"] < 0.75 * ref["area"]):
            warnings.append(f"footprint: ground-floor outline ({footprint['area'] if footprint else None} m2) is much smaller than typical-floor outline ({ref['area']} m2); "
                            "ground floor is open/glazed so the typical-floor outline was used (confidence reduced)")
            ref["confidence"] = min(ref["confidence"], 0.5)
            ref["extra"]["note"] = "typical-floor outline used because the ground-floor linework is incomplete"
            ref["extra"]["ground_floor_outline"] = footprint
            footprint = ref
    else:
        warnings.append("footprint: no ground-floor plan view identified")
    site_fp = None
    if parcel is not None:
        sv = next(v for v in views if v["id"] == parcel["view_id"])
        from shapely.geometry import Polygon as _P
        clip = _P([(x / vf[sv["id"]], y / vf[sv["id"]]) for x, y in parcel["polygon"]]).buffer(0)
        site_fp = analysis.extract_footprint(scene, sv, roles, vf[sv["id"]], warnings, glazing=False, clip=clip)
        if site_fp is None:
            warnings.append("site footprint: building outline in the site plan not derivable")

    counter = [0]
    rooms: list[dict] = []
    for v in views:
        if v["kind"] == "floor_plan":
            rooms += analysis.extract_rooms(scene, v, roles, vf[v["id"]], counter, warnings)
    if not rooms:
        warnings.append("rooms: none extracted (no room-name labels paired with enclosed wall polygons)")

    walls, doors, windows, stairs, dims, levels = [], [], [], [], [], []
    for v in views:
        f = vf[v["id"]]
        if v["kind"] == "floor_plan":
            for e in scene.ents:
                if e.get("view") == v["id"] and roles.get(e["layer"]) == "wall" and e["t"] == "POLY" and not e.get("blk") and len(e["pts"]) >= 2:
                    pl = geom.entity_lines(e)[0][0]
                    walls.append({"view_id": v["id"], "layer": e["layer"], "polyline": [_mm(p, f) for p in pl], "thickness": None})
            # stairs: bbox of stair-layer linework
            st = [e for e in scene.ents if e.get("view") == v["id"] and roles.get(e["layer"]) == "stair" and e["t"] in ("LINE", "POLY")]
            if st:
                from shapely.geometry import box as _box
                from shapely.ops import unary_union
                from .views import cluster_boxes
                import numpy as np
                bbs = np.array([e["bb"] for e in st])
                lab = cluster_boxes(bbs, 60.0 / f)
                for k in set(lab):
                    m = bbs[lab == k]
                    if (lab == k).sum() < 6:
                        continue
                    bb = [m[:, 0].min(), m[:, 1].min(), m[:, 2].max(), m[:, 3].max()]
                    w = sorted([(bb[2] - bb[0]) * f, (bb[3] - bb[1]) * f])
                    stairs.append({"view_id": v["id"], "bbox": [round(x * f, 3) for x in bb], "width": None, "riser_count": None, "tread_depth": None,
                                   "layer": "/".join(sorted({e["layer"] for e, l in zip(st, lab) if l == k})), "extra": {"lines": int((lab == k).sum()), "size_m": [round(w[0], 2), round(w[1], 2)]}})
            # door / window tags like "90/220-K2", "CMK1-120/270"
            for t in scene.texts:
                if t.get("view") != v["id"] or t.get("blk"):
                    continue
                s = t["text"].strip()
                m = re.match(r"^(\d{2,3})\s*/\s*(\d{2,3})\s*-\s*([A-Za-z]{1,4})\d*$", s)
                if m and us == 0.01:
                    w_, h_ = int(m.group(1)) / 100.0, int(m.group(2)) / 100.0
                    code = m.group(3).upper()
                    d = {"view_id": v["id"], "position": _mm(t["pos"], f), "width": w_, "height": h_, "layer": t["layer"], "extra": {"tag": s, "source": "tag text (position = tag position, not symbol)"}}
                    (windows if code.startswith(("PN", "P", "CM")) and not code.startswith("PK") else doors).append(d)
                    continue
                m = re.match(r"^(CMK|PVC|PEN)\w*\s*-\s*(\d{2,4})\s*/\s*(\d{2,4})$", s, re.I)
                if m and us == 0.01:
                    windows.append({"view_id": v["id"], "position": _mm(t["pos"], f), "width": int(m.group(2)) / 100.0, "height": int(m.group(3)) / 100.0, "layer": t["layer"],
                                    "extra": {"tag": s, "source": "tag text"}})
            for i in scene.inserts:
                if i.get("view") == v["id"] and roles.get(i["layer"]) in ("door", "window") and i["name"] in scene.raw.blocks:
                    pts = [p for e in scene.raw.blocks[i["name"]] for pp, _ in geom.entity_lines(e) for p in pp]
                    if pts:
                        xs = [p[0] for p in pts]
                        ys = [p[1] for p in pts]
                        w_ = max(max(xs) - min(xs), max(ys) - min(ys)) * abs(i["sx"]) * f / v["scale_factor"] * v["scale_factor"]
                        if 0.5 <= w_ <= 3.5:
                            doors.append({"view_id": v["id"], "position": _mm(i["pos"], f), "width": round(w_, 3), "height": None, "layer": i["layer"],
                                          "extra": {"block": i["name"], "source": "block extents (leaf+frame)"}})
        for e in scene.ents:
            if e.get("view") == v["id"] and e["t"] == "DIM" and e["measurement"] > 0 and not e.get("blk"):
                dims.append({"view_id": v["id"], "p1": _mm(e["p1"], f), "p2": _mm(e["p2"], f),
                             "measurement": round(e["measurement"] * us, 4), "text": e["text"] or str(round(e["measurement"], 2)), "layer": e["layer"]})
        for t in scene.texts:
            if t.get("view") == v["id"]:
                lv = vocab.parse_level_text(t["text"])
                if lv is not None:
                    levels.append({"view_id": v["id"], "text": t["text"].strip(), "elevation": lv, "position": _mm(t["pos"], f)})
    # texts: meaningful ones
    texts = []
    for t in scene.texts:
        s = t["text"].strip()
        if len(s) >= 2 and not t.get("from_attrib"):
            texts.append({"text": s, "position": _mm(t["pos"], vf.get(t.get("view"), us)), "layer": t["layer"], "height": round((t["h"] or 0) * us, 4),
                          "view_id": t.get("view")})
    texts.sort(key=lambda t: -t["height"])
    texts = texts[:2000]

    out_views = []
    for v in views:
        f = vf[v["id"]]
        b = v["bbox_raw"]
        out_views.append({"id": v["id"], "kind": v["kind"], "name": v["name"], "level_hint": v["level_hint"], "elevation": None,
                          "bbox": [round(b[0] * f, 3), round(b[1] * f, 3), round(b[2] * f, 3), round(b[3] * f, 3)],
                          "extra": {"bbox_raw": [round(x, 3) for x in b], "scale_factor": v["scale_factor"], "scale_source": v["scale_source"],
                                    "scale_denominator": v.get("scale_denominator"), "parent": v.get("parent"), "source": v["source"],
                                    "metric_frame": "metres = raw * unit_scale_to_m * scale_factor"}})
    n_attr = sum(len(i.get("attribs", [])) for i in raw.entities if i["t"] == "INSERT")
    model = {
        "schema_version": "1",
        "source": {"kind": raw.kind, "file": raw.file, "dwg_version": raw.version, "units": units["units"], "unit_scale_to_m": units["unit_scale_to_m"],
                   "unit_source": units["unit_source"], "entity_count": len(raw.entities) + n_attr, "extra": {"unit_evidence": units["evidence"],
                   "type_counts": raw.raw_type_counts}},
        "layers": layers, "views": out_views, "parcel": parcel, "footprint": footprint, "rooms": rooms, "walls": walls, "doors": doors, "windows": windows,
        "stairs": stairs, "dimensions": dims, "levels": levels, "texts": texts, "warnings": warnings,
        "extra": {"site_footprint": site_fp},
    }
    if raw.kind == "dwg" and raw.header.get("EXTMAX") and raw.header["EXTMAX"][2] > 1 and not scene.ents:
        pass
    _add_3d_note(raw, model)
    if raw.raw_type_counts.get('3DSOLID'):
        from shapely.geometry import Polygon as _Pg
        us_ = model['source']['unit_scale_to_m']
        cp = []
        for e in scene.ents:
            if e['t'] == 'POLY' and e['closed'] and len(e['pts']) >= 3 and not e.get('blk'):
                pg = _Pg([(x * us_, y * us_) for x, y, _ in e['pts']])
                cp.append({'layer': e['layer'], 'area': round(pg.area, 2), 'polygon': [[round(x, 3), round(y, 3)] for x, y in pg.exterior.coords][:-1]})
        model['extra']['closed_polylines'] = cp
        model['warnings'].append('parcel/footprint/rooms not derivable: file holds site 3D solids (roads, kerbs, walls, roof) and only a few 2D polylines; closed polylines listed in extra.closed_polylines')
    if _debug is not None:
        _debug.update({"scene": scene, "views": views, "roles": roles, "vf": vf})
    return model


def _add_3d_note(raw, model):
    c = raw.raw_type_counts
    n3 = c.get("3DSOLID", 0) + c.get("3DFACE", 0) + c.get("OTHER", 0)
    if c.get("3DSOLID", 0) > 0:
        model["warnings"].append(f"{c.get('3DSOLID')} 3DSOLID and {c.get('3DFACE', 0)} 3DFACE entities cannot be read (ACIS data not decoded by LibreDWG); only 2D linework/polylines were analysed")
        eh = raw.header.get("EXTMIN"), raw.header.get("EXTMAX")
        if eh[0] and eh[1]:
            sc = model["source"]["unit_scale_to_m"]
            model["extra"]["header_extents_m"] = {"min": [round(v * sc, 2) for v in eh[0]], "max": [round(v * sc, 2) for v in eh[1]],
                                                  "note": "$EXTMIN/$EXTMAX include 3D solids; z-span approximates total building height"}
