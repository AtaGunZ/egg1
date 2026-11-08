"""Hand-built fixture: a small two-storey 'box house' (BuildingModel + GLB + findings + DrawingModel).

Used by the API tests (via StubBackend) and for developing the UI before the real ingest/engine existed.
Run ``python tests/server/fixture_house.py`` to (re)write tests/server/fixtures/*.
The house is deliberately asymmetric (balcony on the south = -y side, chimney at +x/+y) so that a mirrored or
rotated viewer is immediately visible.
"""
from __future__ import annotations

import json
import struct
from pathlib import Path

FIX = Path(__file__).parent / "fixtures"


def G(n: int) -> str:
    return f"FIXTURE{n:015d}"[:22]


S0, S1 = "STOREY0000000000000000", "STOREY1111111111111111"
# (guid, ifc_class, kind, name, storey, (min xyz), (max xyz), rgba)
ELEMS = [
    (G(1), "IfcSlab", "slab", "Ground slab", S0, (0, 0, -0.2), (10, 8, 0), (0.62, 0.62, 0.6, 1)),
    (G(2), "IfcWall", "wall", "Wall S 0", S0, (0, 0, 0), (10, 0.25, 2.8), (0.85, 0.82, 0.75, 1)),
    (G(3), "IfcWall", "wall", "Wall N 0", S0, (0, 7.75, 0), (10, 8, 2.8), (0.85, 0.82, 0.75, 1)),
    (G(4), "IfcWall", "wall", "Wall W 0", S0, (0, 0.25, 0), (0.25, 7.75, 2.8), (0.85, 0.82, 0.75, 1)),
    (G(5), "IfcWall", "wall", "Wall E 0", S0, (9.75, 0.25, 0), (10, 7.75, 2.8), (0.85, 0.82, 0.75, 1)),
    (G(6), "IfcWall", "wall", "Partition 0", S0, (6, 0.25, 0), (6.15, 7.75, 2.8), (0.9, 0.9, 0.88, 1)),
    (G(7), "IfcSlab", "slab", "Floor 1 slab", S1, (0, 0, 2.8), (10, 8, 3.0), (0.62, 0.62, 0.6, 1)),
    (G(8), "IfcWall", "wall", "Wall S 1", S1, (0, 0, 3.0), (10, 0.25, 5.8), (0.85, 0.82, 0.75, 1)),
    (G(9), "IfcWall", "wall", "Wall N 1", S1, (0, 7.75, 3.0), (10, 8, 5.8), (0.85, 0.82, 0.75, 1)),
    (G(10), "IfcWall", "wall", "Wall W 1", S1, (0, 0.25, 3.0), (0.25, 7.75, 5.8), (0.85, 0.82, 0.75, 1)),
    (G(11), "IfcWall", "wall", "Wall E 1", S1, (9.75, 0.25, 3.0), (10, 7.75, 5.8), (0.85, 0.82, 0.75, 1)),
    (G(12), "IfcCovering", "covering", "Ceiling 0", S0, (0.25, 0.25, 2.6), (9.75, 7.75, 2.8), (0.95, 0.95, 0.95, 1)),
    (G(13), "IfcCovering", "covering", "Ceiling 1", S1, (0.25, 0.25, 5.6), (9.75, 7.75, 5.8), (0.95, 0.95, 0.95, 1)),
    (G(14), "IfcRoof", "roof", "Roof", S1, (-0.4, -0.4, 5.8), (10.4, 8.4, 6.2), (0.55, 0.25, 0.2, 1)),
    (G(15), "IfcDoor", "door", "Entrance door", S0, (2, -0.05, 0), (2.9, 0.3, 2.1), (0.4, 0.26, 0.13, 1)),
    (G(16), "IfcWindow", "window", "Window living", S0, (4, -0.05, 0.9), (5.5, 0.3, 2.1), (0.55, 0.8, 0.95, 0.35)),
    (G(17), "IfcWindow", "window", "Window bedroom", S1, (3, -0.05, 3.9), (4.2, 0.3, 5.0), (0.55, 0.8, 0.95, 0.35)),
    (G(18), "IfcSlab", "slab", "Balcony", S1, (6, -2, 2.8), (9, 0, 3.0), (0.7, 0.7, 0.68, 1)),
    (G(19), "IfcRailing", "railing", "Balcony railing", S1, (6, -2, 3.0), (9, -1.95, 4.0), (0.3, 0.3, 0.35, 1)),
    (G(20), "IfcBuildingElementProxy", "other", "Chimney", S1, (8.2, 6.4, 5.8), (9, 7.2, 7.4), (0.4, 0.2, 0.18, 1)),
    (G(21), "IfcSpace", "space", "Living room", S0, (0.25, 0.25, 0), (6, 7.75, 2.6), (0.4, 0.7, 0.9, 0.2)),
    (G(22), "IfcSpace", "space", "Bedroom 1", S0, (6.15, 0.25, 0), (9.75, 7.75, 2.45), (0.4, 0.9, 0.5, 0.2)),
    (G(23), "IfcSpace", "space", "Bedroom 2", S1, (0.25, 0.25, 3.0), (9.75, 7.75, 5.6), (0.9, 0.7, 0.4, 0.2)),
    (G(24), "IfcStair", "stair", "Stair", S0, (6.3, 5.0, 0), (7.5, 7.6, 2.8), (0.6, 0.6, 0.6, 1)),
]


def _box(lo, hi):
    """Vertices (Z-up data coords) -> glTF Y-up positions, normals, indices."""
    x0, y0, z0 = lo
    x1, y1, z1 = hi
    faces = [  # (normal, 4 corners CCW seen from outside) in Z-up
        ((0, 0, 1), [(x0, y0, z1), (x1, y0, z1), (x1, y1, z1), (x0, y1, z1)]),
        ((0, 0, -1), [(x0, y1, z0), (x1, y1, z0), (x1, y0, z0), (x0, y0, z0)]),
        ((0, -1, 0), [(x0, y0, z0), (x1, y0, z0), (x1, y0, z1), (x0, y0, z1)]),
        ((0, 1, 0), [(x1, y1, z0), (x0, y1, z0), (x0, y1, z1), (x1, y1, z1)]),
        ((-1, 0, 0), [(x0, y1, z0), (x0, y0, z0), (x0, y0, z1), (x0, y1, z1)]),
        ((1, 0, 0), [(x1, y0, z0), (x1, y1, z0), (x1, y1, z1), (x1, y0, z1)]),
    ]
    pos, nor, idx = [], [], []
    for n, c in faces:
        b = len(pos)
        for (x, y, z) in c:
            pos.append((x, z, -y))  # Z-up -> Y-up
            nor.append((n[0], n[2], -n[1]))
        idx += [b, b + 1, b + 2, b, b + 2, b + 3]
    return pos, nor, idx


def build_glb(path: Path) -> dict:
    bin_ = bytearray()
    views, accs, meshes, mats, nodes = [], [], [], [], []
    tris = 0

    def add(data: bytes, target: int) -> int:
        while len(bin_) % 4:
            bin_.append(0)
        views.append({"buffer": 0, "byteOffset": len(bin_), "byteLength": len(data), "target": target})
        bin_.extend(data)
        return len(views) - 1

    for i, (guid, cls, kind, name, storey, lo, hi, rgba) in enumerate(ELEMS):
        pos, nor, idx = _box(lo, hi)
        pv = add(b"".join(struct.pack("<3f", *p) for p in pos), 34962)
        nv = add(b"".join(struct.pack("<3f", *p) for p in nor), 34962)
        iv = add(b"".join(struct.pack("<H", k) for k in idx), 34963)
        a0 = len(accs)
        xs = [p[0] for p in pos]
        ys = [p[1] for p in pos]
        zs = [p[2] for p in pos]
        accs.append({"bufferView": pv, "componentType": 5126, "count": len(pos), "type": "VEC3",
                     "min": [min(xs), min(ys), min(zs)], "max": [max(xs), max(ys), max(zs)]})
        accs.append({"bufferView": nv, "componentType": 5126, "count": len(nor), "type": "VEC3"})
        accs.append({"bufferView": iv, "componentType": 5123, "count": len(idx), "type": "SCALAR"})
        mat = {"pbrMetallicRoughness": {"baseColorFactor": list(rgba), "metallicFactor": 0, "roughnessFactor": 0.9},
               "doubleSided": True}
        if rgba[3] < 1:
            mat["alphaMode"] = "BLEND"
        mats.append(mat)
        meshes.append({"primitives": [{"attributes": {"POSITION": a0, "NORMAL": a0 + 1}, "indices": a0 + 2, "material": i}]})
        nodes.append({"name": guid, "mesh": i,
                      "extras": {"guid": guid, "ifc_class": cls, "kind": kind, "storey_id": storey, "name": name}})
        tris += len(idx) // 3
    while len(bin_) % 4:
        bin_.append(0)
    gltf = {"asset": {"version": "2.0", "generator": "bimcheck-fixture"}, "scene": 0,
            "scenes": [{"nodes": list(range(len(nodes)))}], "nodes": nodes, "meshes": meshes, "materials": mats,
            "accessors": accs, "bufferViews": views, "buffers": [{"byteLength": len(bin_)}]}
    js = json.dumps(gltf, separators=(",", ":")).encode()
    js += b" " * (-len(js) % 4)
    total = 12 + 8 + len(js) + 8 + len(bin_)
    path.write_bytes(struct.pack("<4sII", b"glTF", 2, total) + struct.pack("<I4s", len(js), b"JSON") + js
                     + struct.pack("<I4s", len(bin_), b"BIN\0") + bytes(bin_))
    return {"nodes": len(nodes), "triangles": tris, "bounds": {"min": [-0.4, -2, -0.2], "max": [10.4, 8.4, 7.4]}}


def building_model() -> dict:
    els = []
    for (guid, cls, kind, name, storey, lo, hi, rgba) in ELEMS:
        m: dict = {}
        if kind == "space":
            m = {"net_floor_area": round((hi[0] - lo[0]) * (hi[1] - lo[1]), 2), "height": hi[2] - lo[2],
                 "usage": "bedroom" if "Bed" in name else "living_room",
                 "min_width": min(hi[0] - lo[0], hi[1] - lo[1]), "has_exterior_window": True}
        elif kind == "door":
            m = {"width": 0.9, "height": 2.1, "is_external": True}
        elif kind == "window":
            m = {"width": 1.5, "height": 1.2, "sill_height": 0.9}
        elif kind == "wall":
            m = {"thickness": 0.25, "is_external": True}
        els.append({"guid": guid, "express_id": 100, "ifc_class": cls, "kind": kind, "name": name, "long_name": None,
                    "object_type": None, "storey_id": storey, "bbox": {"min": list(lo), "max": list(hi)},
                    "anchor": [(lo[i] + hi[i]) / 2 for i in range(3)], "props": {"IsExternal": kind == "wall"},
                    "measures": m, "provenance": {k: "geometry" for k in m}})
    return {"schema_version": "1",
            "source": {"kind": "ifc", "file": "house.ifc", "ifc_schema": "IFC4", "application": "fixture",
                       "length_unit": "METRE", "length_unit_scale_to_m": 1.0},
            "project": {"name": "Box house", "site_name": None, "building_name": None},
            "storeys": [{"id": S0, "name": "Ground floor", "index": 0, "elevation": 0.0, "height": 3.0, "is_underground": False},
                        {"id": S1, "name": "First floor", "index": 1, "elevation": 3.0, "height": None, "is_underground": False}],
            "elements": els, "summary": {"counts": {"space": 3, "wall": 10, "door": 1}, "warnings": []}}


def drawing_model() -> dict:
    return {"schema_version": "1",
            "source": {"kind": "dxf", "file": "plan.dxf", "units": "m", "unit_scale_to_m": 1.0,
                       "unit_source": "header", "entity_count": 10},
            "layers": [{"name": "duvar", "entity_count": 4, "role": "wall", "role_confidence": 0.9, "role_source": "name"}],
            "views": [{"id": "v1", "kind": "floor_plan", "name": "ZEMIN KAT PLANI", "level_hint": 0, "elevation": None,
                       "bbox": [-10, -10, 30, 30]}],
            "parcel": {"polygon": [[-5, -6], [15, -6], [15, 14], [-5, 14]], "area": 400.0, "layer": "arsa",
                       "view_id": "v1", "source": "polyline"},
            "footprint": {"polygon": [[0, 0], [10, 0], [10, 8], [0, 8]], "area": 80.0, "view_id": "v1", "confidence": 0.8},
            "rooms": [{"id": "r1", "view_id": "v1", "name": "SALON", "usage": "living_room",
                       "polygon": [[0.25, 0.25], [6, 0.25], [6, 7.75], [0.25, 7.75]], "area": 43.1,
                       "labelled_area": None, "min_width": 5.75, "label_point": [3, 4], "confidence": 0.8}],
            "walls": [{"view_id": "v1", "layer": "duvar", "polyline": [[0, 0], [10, 0], [10, 8], [0, 8], [0, 0]], "thickness": 0.25}],
            "doors": [{"view_id": "v1", "position": [2.45, 0], "width": 0.9, "height": None, "layer": "kapi"}],
            "windows": [{"view_id": "v1", "position": [4.75, 0], "width": 1.5, "height": None, "layer": "pencere"}],
            "stairs": [], "dimensions": [], "levels": [], "texts": [], "warnings": []}


def findings() -> dict:
    fl: list[dict] = []

    def f(rule, art, par, status, title, msg, cat="rooms", sev="error", guids=(), ctx=(), storey=(S0, "Ground floor"),
          measured=None, required=None, reason=None, hint=None, dims=(), src="building_model", view=None, anchor=None,
          excerpt=None):
        fl.append({"id": f"{rule}:{(list(guids) or ['model'])[0]}", "rule_id": rule, "article": art, "paragraph": par,
                   "title_tr": title[0], "title_en": title[1], "category": cat, "status": status, "severity": sev,
                   "message_en": msg, "message_tr": msg, "measured": measured, "required": required,
                   "review_reason": reason, "review_hint": hint, "element_guids": list(guids),
                   "storey_id": storey[0], "storey_name": storey[1],
                   "highlight": [{"guid": g, "role": "offending"} for g in guids] + [{"guid": g, "role": "context"} for g in ctx],
                   "anchor": anchor, "dimensions": list(dims),
                   "regulation_excerpt": excerpt or f"Madde {art} fikra {par}: ...", "source": src, "view_id": view})

    f("KBB-28-4", 28, "4", "violation", ("Iskan edilen katlarin ic yuksekligi", "Clear height of occupied storeys"),
      "Bedroom 'Bedroom 1' is 2.45 m high; minimum is 2.60 m", cat="heights", guids=[G(22)], ctx=[G(12)],
      measured={"value": 2.45, "unit": "m", "provenance": "geometry"}, required={"op": ">=", "value": 2.6, "unit": "m"},
      anchor=[7.9, 4, 1.2], dims=[{"p1": [8, 4, 0], "p2": [8, 4, 2.45], "label": "2.45 m", "kind": "clearance"}],
      excerpt="Konut yapilarinda iskan edilen katlarda ic yukseklik en az 2.60 m olmalidir.")
    f("KBB-31-2", 31, "2", "violation", ("Kapi genisligi", "Entrance door width"),
      "Entrance door is 0.90 m wide; minimum is 1.10 m", cat="openings", guids=[G(15)],
      measured={"value": 0.9, "unit": "m", "provenance": "property"}, required={"op": ">=", "value": 1.1, "unit": "m"},
      anchor=[2.45, 0, 1], dims=[{"p1": [2, -0.1, 1.05], "p2": [2.9, -0.1, 1.05], "label": "0.90 m", "kind": "linear"}])
    f("KBB-30-1", 30, "1", "review", ("Pencere alani", "Window area vs floor area"),
      "Window area of 'Living room' could not be measured", cat="openings", sev="warning", guids=[G(21)], ctx=[G(16)],
      reason="missing_measure", hint="Check that windows are modelled with quantities",
      required={"op": ">=", "value": 0.125, "unit": "ratio"}, anchor=[3, 4, 1.2])
    f("KBB-45-1", 45, "1", "review", ("Balkon cikmasi", "Balcony projection"),
      "Balcony projects 2.00 m; judgement needed on parcel setback", cat="setbacks", sev="warning", guids=[G(18)],
      ctx=[G(19)], storey=(S1, "First floor"), reason="legal_judgement", hint="Check plan notes of the parcel",
      measured={"value": 2.0, "unit": "m", "provenance": "geometry"}, required={"op": "<=", "value": 1.5, "unit": "m"},
      anchor=[7.5, -1, 3.5], dims=[{"p1": [6, 0, 3.5], "p2": [6, -2, 3.5], "label": "2.00 m", "kind": "linear"}])
    f("KBB-28-4", 28, "4", "pass", ("Iskan edilen katlarin ic yuksekligi", "Clear height of occupied storeys"),
      "Living room is 2.60 m high", cat="heights", sev="info", guids=[G(21)],
      measured={"value": 2.6, "unit": "m", "provenance": "geometry"}, required={"op": ">=", "value": 2.6, "unit": "m"},
      anchor=[3, 4, 1.3])
    f("KBB-23-1", 23, "1", "violation", ("On bahce mesafesi", "Front garden setback"),
      "Front setback is 4.00 m; minimum is 5.00 m", cat="setbacks", storey=(None, None),
      measured={"value": 4.0, "unit": "m", "provenance": "geometry"}, required={"op": ">=", "value": 5.0, "unit": "m"},
      src="drawing_model", view="v1", anchor=[5, -3, 0],
      dims=[{"p1": [5, 0, 0], "p2": [5, -4, 0], "label": "4.00 m", "kind": "linear"}])
    fl[-1]["id"] = "KBB-23-1:parcel"
    return {"schema_version": "1",
            "summary": {"violation": 3, "review": 2, "pass": 1, "not_applicable": 0, "rules_evaluated": 6,
                        "rules_skipped_manual": 30, "errors": []},
            "findings": fl}


def write_all() -> None:
    FIX.mkdir(parents=True, exist_ok=True)
    build_glb(FIX / "house.glb")
    (FIX / "house.building_model.json").write_text(json.dumps(building_model(), indent=1), encoding="utf-8")
    (FIX / "house.drawing_model.json").write_text(json.dumps(drawing_model(), indent=1), encoding="utf-8")
    (FIX / "house.findings.json").write_text(json.dumps(findings(), indent=1), encoding="utf-8")
    (FIX / "house.ifc").write_text("ISO-10303-21;\nHEADER;\nENDSEC;\nDATA;\nENDSEC;\nEND-ISO-10303-21;\n", encoding="utf-8")
    (FIX / "plan.dxf").write_text("0\nSECTION\n2\nENTITIES\n0\nENDSEC\n0\nEOF\n", encoding="utf-8")


if __name__ == "__main__":
    write_all()
    print("fixtures written to", FIX)
