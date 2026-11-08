"""IFC ingest (S2): ifcopenshell -> BuildingModel dict (+ GLB export). See README.md and docs/CONTRACTS.md."""
from __future__ import annotations

import os
import time
from collections import Counter

import ifcopenshell
import numpy as np

from . import _geometry as G
from ._glb import GlbBuilder
from ._model import SCHEMA_VERSION, Builder, _r, kind_of
from ._units import Units

__all__ = ["extract_building_model", "export_geometry_glb"]


def _open(path):
    path = os.fspath(path)
    if not os.path.isfile(path):
        raise FileNotFoundError(path)
    return ifcopenshell.open(path)


def _application(ifc):
    try:
        apps = ifc.by_type("IfcApplication")
        if apps:
            a = apps[0]
            return " ".join(str(x) for x in (a.ApplicationFullName, a.Version) if x) or None
    except Exception:
        pass
    try:
        hdr = ifc.wrapped_data.header.file_name
        return hdr.originating_system or None
    except Exception:
        return None


def extract_building_model(path) -> dict:
    """Parse an IFC file (IFC2X3 / IFC4 / IFC4X3) into the BuildingModel dict of CONTRACTS section 1."""
    path = os.fspath(path)
    t0 = time.time()
    warnings: list[str] = []
    ifc = _open(path)
    units = Units(ifc, warnings)
    geoms = G.load_geometry(ifc, warnings, cache_key=G.file_cache_key(path))
    b = Builder(ifc, path, units, warnings, geoms)
    b.run()

    project = (ifc.by_type("IfcProject") or [None])[0]
    site = (ifc.by_type("IfcSite") or [None])[0]
    building = (ifc.by_type("IfcBuilding") or [None])[0]
    counts = Counter(e["kind"] for e in b.elements)
    model = {
        "schema_version": SCHEMA_VERSION,
        "source": {
            "kind": "ifc", "file": os.path.basename(path), "ifc_schema": ifc.schema,
            "application": _application(ifc),
            "length_unit": units.length_name, "length_unit_scale_to_m": units.length,
        },
        "project": {
            "name": (project.Name or project.LongName) if project is not None else None,
            "site_name": (site.Name or site.LongName) if site is not None else None,
            "building_name": (building.Name or building.LongName) if building is not None else None,
        },
        "storeys": b.storeys,
        "elements": b.elements,
        "summary": {"counts": dict(sorted(counts.items())), "warnings": warnings,
                    "extra": {"elapsed_s": round(time.time() - t0, 2), "geometry_products": len(geoms)}},
    }
    return model


def export_geometry_glb(path, out_path, *, storey_filter=None) -> dict:
    """Write the model geometry as GLB (Y-up, metres, one node per product named by GlobalId).

    ``storey_filter``: optional iterable of storey GlobalIds / names / indexes; only products of those storeys
    are written. Returns {"nodes", "triangles", "bounds": {"min","max"} (IFC world Z-up), ...}."""
    path = os.fspath(path)
    warnings: list[str] = []
    ifc = _open(path)
    units = Units(ifc, warnings)
    geoms = G.load_geometry(ifc, warnings, cache_key=G.file_cache_key(path))
    b = Builder(ifc, path, units, warnings, geoms)
    index = b.quick_index()

    allowed = None
    if storey_filter is not None:
        if isinstance(storey_filter, (str, int)):
            storey_filter = [storey_filter]
        allowed = set()
        for f in storey_filter:
            for s in b.storeys:
                if f == s["id"] or f == s["name"] or (isinstance(f, int) and not isinstance(f, bool) and f == s["index"]):
                    allowed.add(s["id"])

    gb = GlbBuilder()
    groups: dict[int, int] = {}
    mins, maxs = [], []
    allmins, allmaxs = [], []
    nodes = 0
    # deterministic order: by storey then class then guid
    items = sorted(index.items(), key=lambda kv: (kv[1]["storey"]["index"] if kv[1]["storey"] else -1, kv[1]["ifc_class"], kv[1]["guid"]))
    for step, info in items:
        if allowed is not None and info["storey_id"] not in allowed:
            continue
        pg = geoms[step]
        is_space = info["kind"] == "space"
        mesh = gb.add_mesh(pg.tri, pg.mat_ids, pg.materials, is_space, info["guid"])
        if mesh is None:
            continue
        extras = {"guid": info["guid"], "ifc_class": info["ifc_class"], "kind": info["kind"],
                  "storey_id": info["storey_id"], "name": info["name"]}
        node = gb.add_node(info["guid"], extras, mesh=mesh)
        gp = info["group_parent"]
        if gp is not None:
            gi = groups.get(gp.id())
            if gi is None:
                pextras = {"guid": gp.GlobalId, "ifc_class": gp.is_a(), "kind": kind_of(gp),
                           "storey_id": info["storey_id"], "name": gp.Name, "group": True}
                gi = gb.add_node(gp.GlobalId, pextras, children=[])
                groups[gp.id()] = gi
                gb.root_children.append(gi)
            gb.nodes[gi]["children"].append(node)
        else:
            gb.root_children.append(node)
        nodes += 1
        a, c = pg.bbox()
        allmins.append(a)
        allmaxs.append(c)
        if info["ifc_class"] != "IfcSite":
            mins.append(a)
            maxs.append(c)
    gb.finish(os.fspath(out_path))
    use_min, use_max = (mins, maxs) if mins else (allmins, allmaxs)
    bounds = None
    bounds_all = None
    if use_min:
        bounds = {"min": [_r(v) for v in np.min(use_min, axis=0)], "max": [_r(v) for v in np.max(use_max, axis=0)]}
        bounds_all = {"min": [_r(v) for v in np.min(allmins, axis=0)], "max": [_r(v) for v in np.max(allmaxs, axis=0)]}
    return {"nodes": nodes, "triangles": gb.triangles, "groups": len(groups), "bounds": bounds,
            "bounds_with_site": bounds_all, "file_bytes": os.path.getsize(out_path), "warnings": warnings}
