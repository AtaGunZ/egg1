"""Tiny hand-built BuildingModel element builders for engine tests."""


def rect(x0, y0, x1, y1):
    return [[x0, y0], [x1, y0], [x1, y1], [x0, y1]]


def space(guid, usage, poly, sid="S0", z=0.0, height=2.7, name=None, **ms):
    xs = [p[0] for p in poly]
    ys = [p[1] for p in poly]
    w = min(max(xs) - min(xs), max(ys) - min(ys))
    area = (max(xs) - min(xs)) * (max(ys) - min(ys))
    m = {"usage": usage, "footprint": poly, "net_floor_area": area, "min_width": w, "height": height, "floor_z": z,
         "has_exterior_window": True, "window_guids": [], "door_guids": []}
    m.update(ms)
    return {"guid": guid, "kind": "space", "ifc_class": "IfcSpace", "name": name or guid, "storey_id": sid,
            "bbox": {"min": [min(xs), min(ys), z], "max": [max(xs), max(ys), z + (height or 2.7)]},
            "anchor": [(min(xs) + max(xs)) / 2, (min(ys) + max(ys)) / 2, z], "props": {}, "measures": m,
            "provenance": {k: "quantity" for k in ("net_floor_area", "min_width", "height")}}


def door(guid, x, y, width, height=2.1, sid="S0", z=0.0, prov="property", **ms):
    m = {"width": width, "height": height, "is_external": False, "is_entrance": False, "space_guids": []}
    m.update(ms)
    return {"guid": guid, "kind": "door", "ifc_class": "IfcDoor", "name": guid, "storey_id": sid,
            "bbox": {"min": [x - width / 2, y - 0.1, z], "max": [x + width / 2, y + 0.1, z + (height or 2.1)]},
            "anchor": [x, y, z + 1.05], "props": {}, "measures": m,
            "provenance": {"width": prov, "height": prov}}


def stair(guid, riser, tread, width=1.2, sid="S0", prov="property"):
    return {"guid": guid, "kind": "stair", "ifc_class": "IfcStair", "name": guid, "storey_id": sid,
            "bbox": {"min": [0, 0, 0], "max": [3, width, 2.8]}, "anchor": [1.5, width / 2, 0], "props": {},
            "measures": {"riser_height": riser, "tread_depth": tread, "width": width},
            "provenance": {"riser_height": prov, "tread_depth": prov, "width": prov}}


def slab(guid, x0, y0, x1, y1, sid="S0", z=0.0):
    return {"guid": guid, "kind": "slab", "ifc_class": "IfcSlab", "name": guid, "storey_id": sid,
            "bbox": {"min": [x0, y0, z - 0.2], "max": [x1, y1, z]}, "anchor": [(x0 + x1) / 2, (y0 + y1) / 2, z],
            "props": {}, "measures": {"area": (x1 - x0) * (y1 - y0), "is_roof": False}, "provenance": {}}


def model(elements, storeys=None):
    storeys = storeys or [
        {"id": "S0", "name": "Ground", "index": 0, "elevation": 0.0, "height": 3.0, "is_underground": False},
        {"id": "S1", "name": "First", "index": 1, "elevation": 3.0, "height": 3.0, "is_underground": False}]
    return {"schema_version": "1", "storeys": storeys, "elements": elements, "summary": {}}
