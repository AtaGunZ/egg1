"""Tessellated geometry access (ifcopenshell.geom, world coordinates, metres) and 2D/3D helpers."""
from __future__ import annotations

import math
import multiprocessing
import os
import threading
from dataclasses import dataclass, field

import numpy as np
import ifcopenshell
import ifcopenshell.geom as geom
from shapely import union_all
from shapely.geometry import MultiPolygon, Polygon
from shapely.geometry.polygon import orient
from shapely.ops import polylabel


@dataclass
class ProductGeom:
    step_id: int
    guid: str
    ifc_class: str
    verts: np.ndarray                 # (n,3) float64, world coords, metres, Z-up
    faces: np.ndarray                 # (m,3) int32
    mat_ids: np.ndarray               # (m,) int32 index into materials, -1 = none
    materials: list = field(default_factory=list)   # [(r,g,b,a, name)]

    @property
    def tri(self) -> np.ndarray:
        return self.verts[self.faces]

    def bbox(self):
        return self.verts.min(axis=0), self.verts.max(axis=0)


_CACHE: dict = {}
_CACHE_LOCK = threading.Lock()


def _material_tuple(mt):
    try:
        d = mt.diffuse
        r, g, b = float(d.r()), float(d.g()), float(d.b())
    except Exception:
        return None
    a = 1.0
    try:
        if mt.has_transparency():
            a = 1.0 - float(mt.transparency)
    except Exception:
        pass
    try:
        name = str(mt.name)
    except Exception:
        name = ""
    return (r, g, b, max(0.0, min(1.0, a)), name)


def load_geometry(ifc: ifcopenshell.file, warnings: list[str], *, cache_key=None,
                  threads: int | None = None) -> dict[int, ProductGeom]:
    """Tessellate every product with a representation. Returns {step_id: ProductGeom}.

    Openings (IfcOpeningElement) are *not* returned (they are only used to cut voids), annotations and
    virtual elements are skipped. Result is cached per (path, mtime, size) so extract + GLB export share it."""
    if cache_key is not None:
        with _CACHE_LOCK:
            hit = _CACHE.get(cache_key)
        if hit is not None:
            return hit[0]
    threads = threads or max(1, min(8, multiprocessing.cpu_count()))
    settings = geom.settings()
    settings.set("use-world-coords", True)
    exclude = []
    for cls in ("IfcOpeningElement", "IfcAnnotation", "IfcVirtualElement", "IfcGrid", "IfcOpeningStandardCase"):
        try:
            exclude.extend(ifc.by_type(cls))
        except Exception:
            pass
    out: dict[int, ProductGeom] = {}
    failed = 0
    try:
        it = geom.iterator(settings, ifc, threads, exclude=exclude or None)
    except Exception as e:
        warnings.append(f"geometry iterator could not be created: {e}")
        return out
    ok = False
    try:
        ok = it.initialize()
    except Exception as e:
        warnings.append(f"geometry iterator failed to initialise: {e}")
    if ok:
        while True:
            try:
                shape = it.get()
                g = shape.geometry
                verts = np.frombuffer(g.verts_buffer, dtype=np.float64).reshape(-1, 3).copy()
                faces = np.frombuffer(g.faces_buffer, dtype=np.int32).reshape(-1, 3).copy()
                mids = np.frombuffer(g.material_ids_buffer, dtype=np.int32).copy()
                mats = [_material_tuple(m) for m in g.materials]
                if len(faces) and len(verts):
                    prod = ifc.by_id(shape.id)
                    out[shape.id] = ProductGeom(shape.id, prod.GlobalId, prod.is_a(), verts, faces, mids,
                                                [m if m is not None else (0.8, 0.8, 0.8, 1.0, "") for m in mats])
            except Exception:
                failed += 1
            try:
                if not it.next():
                    break
            except Exception:
                failed += 1
                break
    if failed:
        warnings.append(f"{failed} product shapes could not be tessellated")
    if cache_key is not None:
        with _CACHE_LOCK:
            _CACHE.clear()
            _CACHE[cache_key] = (out,)
    return out


def file_cache_key(path: str):
    try:
        st = os.stat(path)
        return (os.path.abspath(path), st.st_mtime_ns, st.st_size)
    except OSError:
        return None


# ---------------------------------------------------------------------------------------------
# 2D helpers
# ---------------------------------------------------------------------------------------------
def tri_polys(tri: np.ndarray, min_area=1e-8):
    """Shapely polygons for the XY projection of an (m,3,3) triangle array."""
    polys = []
    p = tri[:, :, :2]
    a = 0.5 * ((p[:, 1, 0] - p[:, 0, 0]) * (p[:, 2, 1] - p[:, 0, 1]) - (p[:, 2, 0] - p[:, 0, 0]) * (p[:, 1, 1] - p[:, 0, 1]))
    for k in np.nonzero(np.abs(a) > min_area)[0]:
        polys.append(Polygon(p[k]))
    return polys


def union_xy(tri: np.ndarray):
    polys = tri_polys(tri)
    if not polys:
        return None
    try:
        u = union_all([pg.buffer(1e-5, join_style=2) for pg in polys]).buffer(-1e-5, join_style=2)
    except Exception:
        return None
    return u


def largest_polygon(geom_):
    if geom_ is None or geom_.is_empty:
        return None
    if isinstance(geom_, Polygon):
        return geom_
    if isinstance(geom_, MultiPolygon):
        return max(geom_.geoms, key=lambda g: g.area)
    polys = [g for g in getattr(geom_, "geoms", []) if isinstance(g, Polygon)]
    return max(polys, key=lambda g: g.area) if polys else None


def triangle_normals(tri: np.ndarray):
    n = np.cross(tri[:, 1] - tri[:, 0], tri[:, 2] - tri[:, 0])
    area2 = np.linalg.norm(n, axis=1)
    with np.errstate(invalid="ignore", divide="ignore"):
        unit = np.where(area2[:, None] > 1e-14, n / area2[:, None], 0.0)
    return unit, area2 * 0.5


def mesh_volume(tri: np.ndarray) -> float:
    v = np.einsum("ij,ij->i", tri[:, 0], np.cross(tri[:, 1], tri[:, 2])).sum() / 6.0
    return float(abs(v))


def rect_info(poly: Polygon):
    """Min-area rotated rectangle -> dict(short, long, center, short_dir, long_dir, corners) or None."""
    if poly is None or poly.is_empty:
        return None
    r = poly.minimum_rotated_rectangle
    if not isinstance(r, Polygon):
        return None
    c = np.array(r.exterior.coords)[:4]
    e0 = c[1] - c[0]
    e1 = c[2] - c[1]
    l0, l1 = float(np.linalg.norm(e0)), float(np.linalg.norm(e1))
    center = c.mean(axis=0)
    if l0 <= l1:
        short, long_, sdir, ldir = l0, l1, e0 / max(l0, 1e-12), e1 / max(l1, 1e-12)
    else:
        short, long_, sdir, ldir = l1, l0, e1 / max(l1, 1e-12), e0 / max(l0, 1e-12)
    return {"short": short, "long": long_, "center": center, "short_dir": sdir, "long_dir": ldir, "corners": c}


def inscribed_circle(poly: Polygon):
    """-> (diameter, (x, y)) of the largest circle inside the polygon."""
    try:
        p = polylabel(poly, tolerance=0.005)
        r = poly.exterior.distance(p)
        for h in poly.interiors:
            r = min(r, h.distance(p))
        return 2.0 * float(r), (float(p.x), float(p.y))
    except Exception:
        return None, None


def clean_ring(poly: Polygon, tol=0.002):
    """CCW exterior ring, simplified, as list of [x,y] (not repeated first point)."""
    p = orient(poly, 1.0)
    s = p.simplify(tol, preserve_topology=True)
    if isinstance(s, Polygon) and not s.is_empty and s.area > 0:
        p = orient(s, 1.0)
    return [[float(x), float(y)] for x, y in list(p.exterior.coords)[:-1]]


def group_levels(values: np.ndarray, gap: float = 0.01):
    """Cluster sorted 1D values; returns list of index arrays."""
    if len(values) == 0:
        return []
    order = np.argsort(values)
    groups, cur = [], [order[0]]
    for a, b in zip(order[:-1], order[1:]):
        if values[b] - values[a] > gap:
            groups.append(np.array(cur))
            cur = [b]
        else:
            cur.append(b)
    groups.append(np.array(cur))
    return groups
