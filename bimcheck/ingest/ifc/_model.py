"""BuildingModel extraction (CONTRACTS section 1)."""
from __future__ import annotations

import math
import os
import re
import time
from collections import Counter, defaultdict

import numpy as np
import ifcopenshell
import ifcopenshell.util.placement as uplace
from shapely.geometry import LineString, Point, Polygon
from shapely.strtree import STRtree

from . import _geometry as G
from ._props import PropBag, norm_key, parse_size_string, read_properties, to_bool
from ._units import Units
from ._usage import classify_space, classify_text, fold

SCHEMA_VERSION = "1"

# ---------------------------------------------------------------------------------------------
# element classification
# ---------------------------------------------------------------------------------------------
_KIND_CLASSES = [
    ("space", ("IfcSpace",)),
    ("wall", ("IfcWall", "IfcCurtainWall")),
    ("roof", ("IfcRoof",)),
    ("slab", ("IfcSlab",)),
    ("door", ("IfcDoor",)),
    ("window", ("IfcWindow",)),
    ("stair", ("IfcStair",)),
    ("railing", ("IfcRailing",)),
    ("covering", ("IfcCovering",)),
    ("column", ("IfcColumn",)),
    ("beam", ("IfcBeam",)),
]
_SKIP_CLASSES = ("IfcOpeningElement", "IfcVirtualElement", "IfcAnnotation", "IfcGrid")

_TERRACE_WORDS = re.compile(r"(terras|teras|balkon|balcon|garten|garden|bahce|hof|yard|patio)")
_ENTRANCE_WORDS = re.compile(r"(haustur|hauseingang|eingang|entrance|entry|main ?door|giris|ana kapi|dis kapi|front door)")


def kind_of(el) -> str:
    for kind, classes in _KIND_CLASSES:
        for c in classes:
            if el.is_a(c):
                return kind
    return "other"


def _r(x, n=4):
    if x is None:
        return None
    try:
        x = float(x)
    except Exception:
        return None
    if x != x or math.isinf(x):
        return None
    return round(x, n)


def _num(x):
    return isinstance(x, (int, float)) and not isinstance(x, bool) and x == x


class Meas:
    """Accumulates measures + provenance for one element."""

    def __init__(self, keys=()):
        self.v = {k: None for k in keys}
        self.p = {}

    def set(self, name, value, prov):
        if value is None:
            self.v.setdefault(name, None)
            return
        if isinstance(value, float):
            value = _r(value)
        self.v[name] = value
        if prov:
            self.p[name] = prov

    def has(self, name):
        return self.v.get(name) is not None


class Builder:
    def __init__(self, ifc, path, units: Units, warnings: list, geoms: dict):
        self.ifc = ifc
        self.path = path
        self.units = units
        self.warnings = warnings
        self.geoms = geoms                       # step_id -> ProductGeom
        self.storeys: list[dict] = []            # model storeys (sorted)
        self.storey_by_step: dict[int, dict] = {}
        self.elements: list[dict] = []
        self.by_step: dict[int, dict] = {}
        self.bags: dict[int, PropBag] = {}
        self.children: dict[int, list] = defaultdict(list)   # parent step -> child entities
        self.parent_of: dict[int, object] = {}
        self.polys: dict[int, Polygon] = {}      # step_id -> 2D footprint (spaces, walls)
        self.rects: dict[int, dict] = {}
        self._warn_counter = Counter()

    # ---- utilities -------------------------------------------------------------------------
    def warn(self, msg, key=None, limit=5):
        key = key or msg[:40]
        self._warn_counter[key] += 1
        c = self._warn_counter[key]
        if c <= limit:
            self.warnings.append(msg)
        elif c == limit + 1:
            self.warnings.append(f"... further warnings of type '{key}' suppressed")

    # ---- spatial structure -------------------------------------------------------------------
    def build_storeys(self):
        raw = []
        for s in self.ifc.by_type("IfcBuildingStorey"):
            elev = None
            src = None
            if s.Elevation is not None:
                elev = float(s.Elevation) * self.units.length
                src = "attribute"
            pz = None
            try:
                if s.ObjectPlacement is not None:
                    pz = float(uplace.get_local_placement(s.ObjectPlacement)[2, 3]) * self.units.length
            except Exception:
                pz = None
            if elev is None:
                elev = pz
                src = "placement"
            elif pz is not None and abs(pz - elev) > 0.01:
                self.warn(f"storey '{s.Name}': Elevation attribute {elev:.3f} m differs from placement z {pz:.3f} m "
                          f"(using the attribute)", key="storey-elev")
            if elev is None:
                self.warn(f"storey '{s.Name}' has no elevation; assuming 0", key="storey-noelev")
                elev, src = 0.0, "assumed"
            raw.append((elev, s, src))
        raw.sort(key=lambda t: (t[0], t[1].Name or ""))
        for i, (elev, s, src) in enumerate(raw):
            name = s.Name or s.LongName or f"Storey {i}"
            nxt = raw[i + 1][0] if i + 1 < len(raw) else None
            height = (nxt - elev) if nxt is not None and nxt - elev > 0.05 else None
            under = elev < -0.05 or bool(re.search(r"(basement|keller|bodenplatte|foundation|fdn|fundament|bodrum|temel)", fold(name)))
            d = {"id": s.GlobalId, "name": name, "index": i, "elevation": _r(elev), "height": _r(height),
                 "is_underground": bool(under)}
            if src != "attribute":
                d["extra"] = {"elevation_source": src}
            self.storeys.append(d)
            self.storey_by_step[s.id()] = d
        if not self.storeys:
            self.warnings.append("model has no IfcBuildingStorey: elements have storey_id = null")

    def storey_of(self, el):
        """Storey dict through containment / aggregation chain, or None. Returns (storey, source)."""
        cur = el
        seen = set()
        hops = 0
        while cur is not None and cur.id() not in seen and hops < 12:
            seen.add(cur.id())
            hops += 1
            nxt = None
            for rel in getattr(cur, "ContainedInStructure", None) or []:
                st = rel.RelatingStructure
                if st is None:
                    continue
                if st.is_a("IfcBuildingStorey"):
                    return self.storey_by_step.get(st.id()), ("containment" if hops == 1 else "aggregation")
                nxt = st
            if nxt is None:
                for rel in getattr(cur, "Decomposes", None) or []:
                    if rel.is_a("IfcRelAggregates"):
                        st = rel.RelatingObject
                        if st is None:
                            continue
                        if st.is_a("IfcBuildingStorey"):
                            return self.storey_by_step.get(st.id()), "aggregation"
                        nxt = st
            cur = nxt
        return None, None

    def storey_by_z(self, z):
        if not self.storeys:
            return None
        best = self.storeys[0]
        for s in self.storeys:
            if s["elevation"] is not None and s["elevation"] <= z + 0.05:
                best = s
        return best

    def next_storey_elevation(self, storey):
        if storey is None:
            return None
        i = storey["index"]
        for s in self.storeys[i + 1:]:
            if s["elevation"] - storey["elevation"] > 0.5:
                return s["elevation"]
        return None

    # ---- main passes -------------------------------------------------------------------------
    def collect_products(self):
        out = []
        seen = set()
        for el in self.ifc.by_type("IfcElement"):
            if any(el.is_a(c) for c in _SKIP_CLASSES):
                continue
            out.append(el)
            seen.add(el.id())
        for el in self.ifc.by_type("IfcSpace"):
            if el.id() not in seen:
                out.append(el)
                seen.add(el.id())
        for el in self.ifc.by_type("IfcSite"):
            if el.id() in self.geoms and el.id() not in seen:
                out.append(el)
        # parent/children map via aggregation
        for rel in self.ifc.by_type("IfcRelAggregates"):
            parent = rel.RelatingObject
            for ch in rel.RelatedObjects or []:
                self.children[parent.id()].append(ch)
                self.parent_of[ch.id()] = parent
        return out

    def descendants(self, el, depth=0):
        res = []
        if depth > 4:
            return res
        for ch in self.children.get(el.id(), []):
            res.append(ch)
            res.extend(self.descendants(ch, depth + 1))
        return res

    def element_bbox(self, el):
        """(min,max) from own geometry or union of descendants' geometry; None if unavailable."""
        mins, maxs = [], []
        pg = self.geoms.get(el.id())
        if pg is not None:
            a, b = pg.bbox()
            mins.append(a)
            maxs.append(b)
        else:
            for d in self.descendants(el):
                pg = self.geoms.get(d.id())
                if pg is not None:
                    a, b = pg.bbox()
                    mins.append(a)
                    maxs.append(b)
        if not mins:
            return None
        return np.min(mins, axis=0), np.max(maxs, axis=0)

    def build(self, products):
        # ---- pass 1: base data --------------------------------------------------------------
        for el in products:
            kind = kind_of(el)
            if el.is_a("IfcStairFlight") and not isinstance(self.parent_of.get(el.id()), type(None)) \
                    and self.parent_of[el.id()].is_a("IfcStair"):
                kind = "other"
            elif el.is_a("IfcStairFlight"):
                kind = "stair"
            bag = read_properties(el, self.units)
            self.bags[el.id()] = bag
            e = {
                "guid": el.GlobalId, "express_id": el.id(), "ifc_class": el.is_a(), "kind": kind,
                "name": el.Name, "long_name": getattr(el, "LongName", None), "object_type": getattr(el, "ObjectType", None),
                "storey_id": None, "bbox": None, "anchor": None,
                "props": {k: v for k, v in bag.flat.items() if v is not None},
                "measures": {}, "provenance": {},
            }
            ex = {}
            parent = self.parent_of.get(el.id())
            if parent is not None and not parent.is_a("IfcBuildingStorey") and not parent.is_a("IfcBuilding") \
                    and not parent.is_a("IfcSite"):
                ex["parent_guid"] = parent.GlobalId
            if self.descendants(el):
                ex["part_guids"] = [d.GlobalId for d in self.descendants(el) if d.id() in self.geoms]
            e["extra"] = ex
            st, src = self.storey_of(el)
            if st is None and parent is not None:
                st, src = self.storey_of(parent)
            bb = self.element_bbox(el)
            if bb is not None:
                e["bbox"] = {"min": [_r(v) for v in bb[0]], "max": [_r(v) for v in bb[1]]}
                e["anchor"] = [_r(v) for v in (bb[0] + bb[1]) / 2.0]
            else:
                # no geometry: use placement origin
                pt = None
                try:
                    if el.ObjectPlacement is not None:
                        m = uplace.get_local_placement(el.ObjectPlacement)
                        pt = [float(m[0, 3]) * self.units.length, float(m[1, 3]) * self.units.length,
                              float(m[2, 3]) * self.units.length]
                except Exception:
                    pt = None
                if pt is not None:
                    e["bbox"] = {"min": [_r(v) for v in pt], "max": [_r(v) for v in pt]}
                    e["anchor"] = [_r(v) for v in pt]
                    ex["bbox_source"] = "placement"
                self.warn(f"{el.is_a()} '{el.Name}' ({el.GlobalId}) has no geometry"
                          + ("" if pt is not None else " and no placement"), key=f"nogeom-{el.is_a()}")
            if st is None and e["bbox"] is not None and self.storeys:
                zref = e["bbox"]["max"][2] - 0.01 if kind in ("slab", "roof") else e["anchor"][2]
                st = self.storey_by_z(zref)
                ex["storey_source"] = "geometry"
            elif st is not None:
                ex["storey_source"] = src
            e["storey_id"] = st["id"] if st else None
            self.elements.append(e)
            self.by_step[el.id()] = e
        self._step_to_ent = {el.id(): el for el in products}

    # ---- measure helpers -------------------------------------------------------------------------
    def entity(self, e):
        return self._step_to_ent[e["express_id"]]

    def storey_dict(self, e):
        for s in self.storeys:
            if s["id"] == e["storey_id"]:
                return s
        return None

    def footprint(self, step_id, kind):
        """2D polygon footprint of a mesh (cached)."""
        if step_id in self.polys:
            return self.polys[step_id]
        pg = self.geoms.get(step_id)
        poly = None
        if pg is not None:
            tri = pg.tri
            if kind == "space":
                n, a = G.triangle_normals(tri)
                down = tri[n[:, 2] < -0.9]
                zlow = pg.verts[:, 2].min()
                lows = down[down[:, :, 2].mean(axis=1) < zlow + 0.06] if len(down) else down
                u_low = G.union_xy(lows) if len(lows) else None
                u_all = G.union_xy(tri)
                if u_low is not None and u_all is not None and u_low.area >= 0.85 * u_all.area:
                    poly = G.largest_polygon(u_low)
                else:
                    poly = G.largest_polygon(u_all)
            else:
                poly = G.largest_polygon(G.union_xy(tri))
        if poly is not None and (poly.is_empty or poly.area < 1e-6):
            poly = None
        self.polys[step_id] = poly
        return poly

    # ---- generic selectors ---------------------------------------------------------------------
    def choose(self, m: Meas, name, bag: PropBag, *, q=(), p=(), attr=None, geom=None, extra_q=None):
        """Strongest-source selection: quantity -> property -> geometry. ``attr`` is (value, label) for
        IFC attributes (provenance property)."""
        v, src = (bag.find_quantity(q) if q else (None, None))
        if v is not None:
            m.set(name, v, "quantity")
            return "quantity"
        if attr is not None and attr[0] is not None and attr[0] > 0:
            m.set(name, attr[0], "property")
            return "property"
        v, src = (bag.find_property(p) if p else (None, None))
        if v is not None:
            m.set(name, v, "property")
            return "property"
        if geom is not None and geom > 0:
            m.set(name, geom, "geometry")
            return "geometry"
        m.set(name, None, None)
        return None

    # ---- kind specific -----------------------------------------------------------------------------
    def measure_wall(self, e, el):
        bag = self.bags[el.id()]
        m = Meas(["thickness", "length", "height", "is_external"])
        pg = self.geoms.get(el.id())
        poly = self.footprint(el.id(), "wall") if pg is not None else None
        g_t = g_l = g_h = None
        if poly is not None:
            ri = G.rect_info(poly)
            if ri is not None:
                self.rects[el.id()] = ri
                if poly.area / max(ri["short"] * ri["long"], 1e-9) >= 0.9:
                    g_t, g_l = ri["short"], ri["long"]
                else:   # bent / non rectangular wall: thin-strip estimate
                    P, A = poly.length, poly.area
                    d = (P / 4) ** 2 - A
                    g_t = P / 4 - math.sqrt(d) if d > 0 else ri["short"]
                    g_l = A / g_t if g_t > 0 else ri["long"]
            g_h = float(pg.verts[:, 2].max() - pg.verts[:, 2].min())
        # thickness: quantity -> material layer usage (property) -> pset -> geometry
        v, _ = bag.find_quantity(["Width", "Thickness", "NominalWidth"])
        if v is not None:
            m.set("thickness", v, "quantity")
        else:
            lt = self.layer_thickness(el)
            if lt:
                m.set("thickness", lt, "property")
            else:
                v, _ = bag.find_property(["Width", "Thickness", "NominalThickness", "Wall Thickness"])
                if v is not None:
                    m.set("thickness", v, "property")
                elif g_t:
                    m.set("thickness", g_t, "geometry")
        self.choose(m, "length", bag, q=["Length", "NominalLength"], p=["Length"], geom=g_l)
        self.choose(m, "height", bag, q=["Height", "NominalHeight", "Wall Height"], p=["Height", "Unconnected Height", "NominalHeight"], geom=g_h)
        return m

    def layer_thickness(self, el):
        try:
            for rel in getattr(el, "HasAssociations", None) or []:
                if rel.is_a("IfcRelAssociatesMaterial"):
                    mat = rel.RelatingMaterial
                    layers = None
                    if mat.is_a("IfcMaterialLayerSetUsage"):
                        layers = mat.ForLayerSet.MaterialLayers
                    elif mat.is_a("IfcMaterialLayerSet"):
                        layers = mat.MaterialLayers
                    elif mat.is_a("IfcMaterialLayer"):
                        layers = [mat]
                    if layers:
                        t = sum(float(l.LayerThickness or 0) for l in layers) * self.units.length
                        if t > 0:
                            return t
        except Exception:
            pass
        return None

    def host_wall(self, el):
        try:
            for rel in getattr(el, "FillsVoids", None) or []:
                op = rel.RelatingOpeningElement
                for v in getattr(op, "VoidsElements", None) or []:
                    return v.RelatingBuildingElement
        except Exception:
            pass
        return None

    def measure_opening(self, e, el, kind):
        bag = self.bags[el.id()]
        keys = ["width", "height", "is_external", "thickness"] if kind == "door" else ["width", "height", "sill_height", "area", "is_external"]
        m = Meas(keys)
        pg = self.geoms.get(el.id())
        g_w = g_h = g_t = None
        if pg is not None:
            poly = G.largest_polygon(G.union_xy(pg.tri))
            ri = G.rect_info(poly) if poly is not None else None
            if ri is not None:
                self.rects[el.id()] = ri
                g_w, g_t = ri["long"], ri["short"]
            g_h = float(pg.verts[:, 2].max() - pg.verts[:, 2].min())
        ow = el.OverallWidth * self.units.length if getattr(el, "OverallWidth", None) else None
        oh = el.OverallHeight * self.units.length if getattr(el, "OverallHeight", None) else None
        wkeys = ["Width", "OverallWidth", "NominalWidth", "Breite"]
        hkeys = ["Height", "OverallHeight", "NominalHeight", "Hoehe"]
        # overall dimensions
        mo = Meas()
        self.choose(mo, "w", bag, q=wkeys, p=wkeys, attr=(ow, "OverallWidth"), geom=g_w)
        self.choose(mo, "h", bag, q=hkeys, p=hkeys, attr=(oh, "OverallHeight"), geom=g_h)
        if kind == "door":
            # ---- clear width: explicit property, else lining-based estimate, else overall
            clear, clear_prov = None, None
            v, _ = bag.find_quantity(["ClearWidth", "Clear Width", "NetWidth", "Lichte Breite", "Durchgangsbreite"])
            if v is not None:
                clear, clear_prov = v, "quantity"
            else:
                v, _ = bag.find_property(["ClearWidth", "Clear Width", "NetWidth", "Lichte Breite", "Durchgangsbreite", "Lichtes Mass"])
                if v is not None:
                    clear, clear_prov = v, "property"
                else:
                    sv, _ = bag.find_property(["Größe Ausgang", "Groesse Ausgang", "Grosse Ausgang", "Lichte Maße", "Clear Opening"],
                                              numeric=False)
                    sz = parse_size_string(sv)
                    if sz:
                        clear, clear_prov = sz[0], "property"
            est = None
            if clear is None and mo.v.get("w"):
                lt, _ = bag.find_property(["LiningThickness"])
                if lt:
                    est = mo.v["w"] - 2 * lt
                    if est <= 0.2:
                        est = None
            if clear is not None:
                m.set("width", clear, clear_prov)
                m.v["width_kind"] = "clear"
            elif est is not None:
                m.set("width", est, "inferred")
                m.v["width_kind"] = "clear_estimated"
            else:
                m.set("width", mo.v.get("w"), mo.p.get("w"))
                m.v["width_kind"] = "overall" if mo.v.get("w") else None
            m.set("overall_width", mo.v.get("w"), mo.p.get("w"))
            m.set("clear_width", clear if clear is not None else None, clear_prov)
            m.set("height", mo.v.get("h"), mo.p.get("h"))
            v, _ = bag.find_quantity(["Thickness", "Depth"])
            if v is None:
                v, _ = bag.find_property(["Thickness", "Depth", "FrameDepth"])
            if v is not None:
                m.set("thickness", v, "property")
            elif g_t:
                m.set("thickness", g_t, "geometry")
        else:
            m.set("width", mo.v.get("w"), mo.p.get("w"))
            m.set("height", mo.v.get("h"), mo.p.get("h"))
            # sill height above storey floor
            st = self.storey_dict(e)
            v, _ = bag.find_property(["Sill Height", "SillHeight", "Sill_Height", "Brüstungshöhe", "Brustungshohe", "Parapet Height"])
            if v is None:
                v, _ = bag.find_quantity(["SillHeight", "Sill Height"], positive=False)
            if v is not None:
                m.set("sill_height", v, "property")
            elif pg is not None and st is not None and st["elevation"] is not None:
                m.set("sill_height", float(pg.verts[:, 2].min()) - st["elevation"], "geometry")
            if m.v.get("width") and m.v.get("height"):
                a, _ = bag.find_quantity(["Area", "GrossArea"])
                if a is not None:
                    m.set("area", a, "quantity")
                else:
                    wp, hp = m.p.get("width"), m.p.get("height")
                    weak = "geometry" if "geometry" in (wp, hp) else ("inferred" if "inferred" in (wp, hp) else "property")
                    m.set("area", m.v["width"] * m.v["height"], weak)
        m.v["is_external"] = None
        ie, src = bag.find_bool(["IsExternal"])
        if ie is not None:
            m.set("is_external", ie, "property")
        return m

    def measure_slab(self, e, el):
        bag = self.bags[el.id()]
        m = Meas(["thickness", "area", "is_roof", "is_floor"])
        pg = self.geoms.get(el.id())
        g_t = g_a = None
        sloped = False
        if pg is not None:
            tri = pg.tri
            n, a = G.triangle_normals(tri)
            if len(a) and a.sum() > 0:
                up = n[:, 2] > 0.5
                if up.any():
                    # dominant (area weighted) up-facing normal
                    w = a[up]
                    nn = (n[up] * w[:, None]).sum(axis=0)
                    nn /= max(np.linalg.norm(nn), 1e-9)
                    sloped = nn[2] < 0.995
                    dom = (n @ nn) > 0.97
                    face_area = a[dom & up].sum()
                    if face_area > 0:
                        g_a = float(face_area)
                        vol = G.mesh_volume(tri)
                        g_t = vol / face_area if vol > 0 else None
                        if g_t is not None and (g_t <= 0.005 or g_t > 3.0):
                            g_t = None
        v, _ = bag.find_quantity(["Width", "Depth", "Thickness"])
        if v is not None:
            m.set("thickness", v, "quantity")
        else:
            lt = self.layer_thickness(el)
            if lt:
                m.set("thickness", lt, "property")
            else:
                v, _ = bag.find_property(["Thickness", "Width", "Default Thickness"])
                if v is not None:
                    m.set("thickness", v, "property")
                elif g_t:
                    m.set("thickness", g_t, "geometry")
        v, _ = bag.find_quantity(["GrossArea", "NetArea", "Area", "GrossSurfaceArea"])
        if v is not None:
            m.set("area", v, "quantity")
        else:
            v, _ = bag.find_property(["Area", "GrossArea", "TotalArea"])
            if v is not None:
                m.set("area", v, "property")
            elif g_a:
                m.set("area", g_a, "geometry")
        pred = str(getattr(el, "PredefinedType", None) or "NOTDEFINED").upper()
        parent = self.parent_of.get(el.id())
        is_roof = None
        if pred in ("ROOF",) or (parent is not None and parent.is_a("IfcRoof")):
            is_roof, rp = True, "property"
        elif pred in ("FLOOR", "BASESLAB", "LANDING"):
            is_roof, rp = False, "property"
        elif pg is not None:
            top = self.storeys[-1]["elevation"] if self.storeys else None
            if sloped and top is not None and pg.verts[:, 2].min() >= top - 0.01:
                is_roof, rp = True, "inferred"
            elif not sloped:
                is_roof, rp = False, "inferred"
        if is_roof is not None:
            m.set("is_roof", is_roof, rp)
            m.set("is_floor", (not is_roof) and (pred in ("FLOOR", "BASESLAB", "LANDING") or not sloped),
                  "property" if pred in ("FLOOR", "BASESLAB", "LANDING") else "inferred")
        if is_roof and pg is not None:
            m.set("max_height_z", float(pg.verts[:, 2].max()), "geometry")
        return m

    def measure_roof(self, e, el):
        bag = self.bags[el.id()]
        m = Meas(["area", "max_height_z"])
        parts = [self.geoms[d.id()] for d in self.descendants(el) if d.id() in self.geoms]
        if el.id() in self.geoms:
            parts.append(self.geoms[el.id()])
        g_a = None
        if parts:
            tot = 0.0
            for pg in parts:
                n, a = G.triangle_normals(pg.tri)
                tot += float(a[n[:, 2] > 0.2].sum())
            g_a = tot or None
        v, _ = bag.find_quantity(["GrossArea", "NetArea", "Area", "TotalArea"])
        if v is not None:
            m.set("area", v, "quantity")
        else:
            v, _ = bag.find_property(["TotalArea", "Area", "ProjectedArea"])
            if v is not None:
                m.set("area", v, "property")
            elif g_a:
                m.set("area", g_a, "geometry")
        if parts:
            m.set("max_height_z", float(max(pg.verts[:, 2].max() for pg in parts)), "geometry")
        else:
            v, _ = bag.find_property(["Maximum Ridge Height"])
        return m

    def measure_covering(self, e, el):
        bag = self.bags[el.id()]
        m = Meas(["covering_type", "area"])
        pred = str(getattr(el, "PredefinedType", None) or "NOTDEFINED").upper()
        mp = {"CEILING": "ceiling", "FLOORING": "floor", "CLADDING": "cladding", "ROOFING": "roofing",
              "INSULATION": "insulation", "MEMBRANE": "membrane", "SLEEVING": "sleeving", "WRAPPING": "wrapping"}
        ctype = mp.get(pred)
        prov = "property"
        if ctype is None:
            txt = fold(" ".join(str(x) for x in (el.Name, el.ObjectType, getattr(el, "Description", None)) if x))
            if re.search(r"(ceiling|decke|tavan|plafond)", txt):
                ctype, prov = "ceiling", "inferred"
            elif re.search(r"(floor|boden|zemin|parke|doseme|estrich|flooring)", txt):
                ctype, prov = "floor", "inferred"
            elif re.search(r"(cladding|fassade|kaplama|verkleidung)", txt):
                ctype, prov = "cladding", "inferred"
            else:
                pg = self.geoms.get(el.id())
                st = self.storey_dict(e)
                if pg is not None and st is not None:
                    n, a = G.triangle_normals(pg.tri)
                    if a.sum() > 0 and abs((n[:, 2] * a).sum()) / a.sum() > 0 and (np.abs(n[:, 2]) > 0.9).sum() > 0:
                        rel = float(pg.verts[:, 2].mean()) - st["elevation"]
                        h = st["height"] or 2.8
                        if rel > 0.6 * h:
                            ctype, prov = "ceiling", "inferred"
                        elif rel < 0.3 * h:
                            ctype, prov = "floor", "inferred"
                if ctype is None:
                    ctype, prov = "other", "inferred"
        m.set("covering_type", ctype, prov)
        pg = self.geoms.get(el.id())
        g_a = None
        if pg is not None:
            n, a = G.triangle_normals(pg.tri)
            g_a = float(a[np.abs(n[:, 2]) > 0.9].sum()) / 2.0 or None
        self.choose(m, "area", bag, q=["GrossArea", "NetArea", "Area", "TotalSurfaceArea"], p=["Area", "GrossArea"], geom=g_a)
        return m

    def measure_railing(self, e, el):
        bag = self.bags[el.id()]
        m = Meas(["height", "length"])
        pg = self.geoms.get(el.id())
        g_h = g_l = None
        if pg is not None:
            g_h = float(pg.verts[:, 2].max() - pg.verts[:, 2].min())
            poly = G.union_xy(pg.tri)
            if poly is not None and not poly.is_empty:
                g_l = float(poly.length) / 2.0
                ri = G.rect_info(G.largest_polygon(poly))
                if ri and ri["long"] > g_l:
                    g_l = ri["long"] if ri["short"] < 0.3 else g_l
        self.choose(m, "height", bag, q=["Height", "RailingHeight", "Railing Height"], p=["Height", "Railing Height", "RailingHeight"], geom=g_h)
        self.choose(m, "length", bag, q=["Length"], p=["Length"], geom=g_l)
        return m

    def measure_simple(self, e, el, kind):
        bag = self.bags[el.id()]
        pg = self.geoms.get(el.id())
        m = Meas()
        if kind == "column" and pg is not None:
            self.choose(m, "height", bag, q=["Length", "Height"], p=["Height"], geom=float(pg.verts[:, 2].max() - pg.verts[:, 2].min()))
        elif kind == "beam" and pg is not None:
            ri = G.rect_info(G.largest_polygon(G.union_xy(pg.tri)))
            self.choose(m, "length", bag, q=["Length"], p=["Length"], geom=ri["long"] if ri else None)
        return m

    # ---- stairs --------------------------------------------------------------------------------------
    def stair_geometry(self, el):
        """Analyse tessellated treads of a stair (all flights). Returns dict or None."""
        parts = []
        ds = [d for d in self.descendants(el) if d.is_a("IfcStairFlight") and d.id() in self.geoms]
        if ds:
            parts = [self.geoms[d.id()] for d in ds]
        elif el.id() in self.geoms:
            parts = [self.geoms[el.id()]]
        if not parts:
            return None
        flights = []
        for pg in parts:
            tri = pg.tri
            n, a = G.triangle_normals(tri)
            mk = (n[:, 2] > 0.985) & (a > 1e-5)
            if mk.sum() < 2:
                continue
            tt = tri[mk]
            zc = tt[:, :, 2].mean(axis=1)
            levels = []
            for gi in G.group_levels(zc, 0.012):
                u = G.union_xy(tt[gi])
                if u is None or u.is_empty:
                    continue
                levels.append((float(zc[gi].mean()), float(u.area), u))
            if len(levels) < 2:
                continue
            amax = max(l[1] for l in levels)
            levels = [l for l in levels if l[1] >= 0.5 * amax]
            levels.sort(key=lambda l: l[0])
            if len(levels) < 2:
                continue
            zs = np.array([l[0] for l in levels])
            diffs = np.diff(zs)
            diffs = diffs[diffs > 0.05]
            if not len(diffs):
                continue
            riser = float(np.median(diffs))
            widths, depths = [], []
            for z, ar, u in levels:
                ri = G.rect_info(G.largest_polygon(u))
                if ri:
                    widths.append(ri["long"])
                    depths.append(ar / ri["long"] if ri["long"] > 0 else ri["short"])
            flights.append({"n_treads": len(levels), "riser": riser, "z_first": float(zs[0]), "z_last": float(zs[-1]),
                            "width": float(np.median(widths)) if widths else None,
                            "depth": float(np.median(depths)) if depths else None,
                            "z_min": float(pg.verts[:, 2].min())})
        if not flights:
            return None
        return {"flights": flights,
                "riser": float(np.median([f["riser"] for f in flights])),
                "width": float(np.median([f["width"] for f in flights if f["width"]] or [np.nan])),
                "depth": float(np.median([f["depth"] for f in flights if f["depth"]] or [np.nan])),
                "n_treads": int(sum(f["n_treads"] for f in flights)),
                "z_min": min(f["z_min"] for f in flights), "z_last": max(f["z_last"] for f in flights)}

    def measure_stair(self, e, el):
        bag = self.bags[el.id()]
        m = Meas(["riser_height", "tread_depth", "width", "step_count", "flight_count", "total_rise", "clear_headroom"])
        flights = [d for d in self.descendants(el) if d.is_a("IfcStairFlight")]
        if el.is_a("IfcStairFlight"):
            flights = [el]
        gres = self.stair_geometry(el)
        # property sources -----------------------------------------------------------------------
        fl_risers = fl_riser_h = fl_tread = None
        steps_attr = []
        rh_attr = []
        td_attr = []
        for f in flights:
            fb = self.bags.get(f.id()) or read_properties(f, self.units)
            nr, _ = fb.find_property(["NumberOfRiser", "NumberOfRisers"])
            if not nr:
                nr = getattr(f, "NumberOfRiser", None) or getattr(f, "NumberOfRisers", None)
            # NOTE: Revit writes the IfcStairFlight RiserHeight/TreadLength *attributes* in feet regardless of the
            # project unit; the Pset values are correct, so psets win over attributes.
            rh = fb.find_property(["RiserHeight"])[0]
            if not rh and getattr(f, "RiserHeight", None):
                rh = f.RiserHeight * self.units.length
            td = fb.find_property(["TreadLength"])[0]
            if not td and getattr(f, "TreadLength", None):
                td = f.TreadLength * self.units.length
            if nr:
                steps_attr.append(int(nr))
            if rh:
                rh_attr.append(float(rh))
            if td:
                td_attr.append(float(td))
        # stair-level attributes (IFC4)
        nr_s = getattr(el, "NumberOfRisers", None)
        if nr_s and not steps_attr:
            steps_attr.append(int(nr_s))
        rh_s = getattr(el, "RiserHeight", None)
        if rh_s and not rh_attr:
            rh_attr.append(float(rh_s) * self.units.length)
        td_s = getattr(el, "TreadLength", None)
        if td_s and not td_attr:
            td_attr.append(float(td_s) * self.units.length)
        v, _ = bag.find_property(["NumberOfRiser", "NumberOfRisers", "Actual Number of Risers"])
        if v and not steps_attr:
            steps_attr.append(int(v))
        v, _ = bag.find_property(["RiserHeight", "Actual Riser Height"])
        if v and not rh_attr:
            rh_attr.append(v)
        v, _ = bag.find_property(["TreadLength", "Actual Tread Depth", "TreadDepth"])
        if v and not td_attr:
            td_attr.append(v)
        # riser height
        qv, _ = bag.find_quantity(["RiserHeight"])
        if qv:
            m.set("riser_height", qv, "quantity")
        elif rh_attr:
            m.set("riser_height", max(rh_attr), "property")
        elif gres:
            m.set("riser_height", gres["riser"], "geometry")
        qv, _ = bag.find_quantity(["TreadLength", "TreadDepth"])
        if qv:
            m.set("tread_depth", qv, "quantity")
        elif td_attr:
            m.set("tread_depth", min(td_attr), "property")
        elif gres and gres["depth"] == gres["depth"]:
            m.set("tread_depth", gres["depth"], "geometry")
        qv, _ = bag.find_quantity(["Width", "StairWidth", "ClearWidth"])
        if qv:
            m.set("width", qv, "quantity")
        else:
            pv, _ = bag.find_property(["Width", "StairWidth", "ClearWidth", "Nominal Width"])
            if pv is None:
                for f in flights:
                    pv, _ = (self.bags.get(f.id()) or PropBag()).find_property(["Width", "StairWidth"])
                    if pv:
                        break
            if pv:
                m.set("width", pv, "property")
            elif gres and gres["width"] == gres["width"]:
                m.set("width", gres["width"], "geometry")
        # step count
        if steps_attr:
            m.set("step_count", int(sum(steps_attr)), "property")
        elif gres:
            st = self.storey_dict(e)
            r = gres["riser"]
            n_tr = gres["n_treads"]
            nfl = len(gres["flights"])
            est = None
            if st is not None:
                E = self.next_storey_elevation(st)
                if E is not None and r > 0:
                    est = int(round((E - st["elevation"]) / r))
                    if not (n_tr <= est <= n_tr + nfl + 1):
                        est = None
            if est is not None:
                m.set("step_count", est, "inferred")
            else:
                m.set("step_count", n_tr + nfl, "inferred")
        if flights:
            m.set("flight_count", len(flights), "property")
        elif gres:
            m.set("flight_count", len(gres["flights"]), "geometry")
        # total rise
        if m.has("step_count") and m.has("riser_height"):
            pr = "property" if m.p.get("step_count") == "property" and m.p.get("riser_height") in ("property", "quantity") else (
                "inferred" if "inferred" in (m.p.get("step_count"),) else "geometry")
            m.set("total_rise", m.v["step_count"] * m.v["riser_height"], pr)
        # cross-check geometry vs declared values
        if gres:
            chk = {"riser_height": _r(gres["riser"]), "tread_depth": _r(gres["depth"]) if gres["depth"] == gres["depth"] else None,
                   "width": _r(gres["width"]) if gres["width"] == gres["width"] else None,
                   "tread_levels": gres["n_treads"], "flights": len(gres["flights"])}
            e["extra"]["geometry_check"] = chk
            for k in ("riser_height", "tread_depth", "width"):
                gv, dv = chk.get(k), m.v.get(k)
                if gv and dv and m.p.get(k) in ("property", "quantity") and abs(gv - dv) / dv > 0.08:
                    self.warn(f"stair '{el.Name}': declared {k} {dv:.3f} m differs from geometry {gv:.3f} m", key="stair-mismatch")
        return m

    # ---- spaces -----------------------------------------------------------------------------------------
    def measure_space(self, e, el):
        bag = self.bags[el.id()]
        m = Meas(["net_floor_area", "gross_floor_area", "perimeter", "height", "floor_z", "ceiling_z", "min_width",
                  "max_length", "footprint", "usage", "usage_source", "door_guids", "window_guids",
                  "has_exterior_window", "window_area", "exterior_wall_guids"])
        pg = self.geoms.get(el.id())
        poly = self.footprint(el.id(), "space") if pg is not None else None
        st = self.storey_dict(e)
        ex = e["extra"]
        g_area = g_per = None
        if poly is not None:
            g_area, g_per = float(poly.area), float(poly.exterior.length)
            ri = G.rect_info(poly)
            if ri:
                m.set("min_width", ri["short"], "geometry")
                m.set("max_length", ri["long"], "geometry")
                c, s_, l_ = ri["center"], ri["short_dir"], ri["long_dir"]
                ex["min_width_segment"] = [[_r(c[0] - s_[0] * ri["short"] / 2), _r(c[1] - s_[1] * ri["short"] / 2)],
                                           [_r(c[0] + s_[0] * ri["short"] / 2), _r(c[1] + s_[1] * ri["short"] / 2)]]
                ex["max_length_segment"] = [[_r(c[0] - l_[0] * ri["long"] / 2), _r(c[1] - l_[1] * ri["long"] / 2)],
                                            [_r(c[0] + l_[0] * ri["long"] / 2), _r(c[1] + l_[1] * ri["long"] / 2)]]
            d, ctr = G.inscribed_circle(poly)
            if d:
                m.set("min_inscribed_width", d, "geometry")
                ex["inscribed_circle"] = {"center": [_r(ctr[0]), _r(ctr[1])], "diameter": _r(d)}
            m.set("footprint", G.clean_ring(poly), "geometry")
            m.set("geometry_floor_area", g_area, "geometry")
            self.rects[el.id()] = ri
            if len(poly.interiors):
                ex["footprint_holes"] = len(poly.interiors)
        # areas -----------------------------------------------------------------------------
        v, src = bag.find_quantity(["NetFloorArea", "NetArea", "Net Floor Area", "FloorArea", "NetFloorAreaBOMA"])
        net_prov = None
        if v is not None:
            m.set("net_floor_area", v, "quantity")
        else:
            v, src = bag.find_quantity(["GSA BIM Area", "Area"])
            if v is not None:
                m.set("net_floor_area", v, "quantity")
            else:
                v, src = bag.find_property(["NetFloorArea", "Net Floor Area", "Area", "Fläche", "Flaeche", "Gemessene Nettofläche"])
                if v is not None:
                    m.set("net_floor_area", v, "property")
                elif g_area:
                    m.set("net_floor_area", g_area, "geometry")
        v, src = bag.find_quantity(["GrossFloorArea", "GrossArea", "Gross Floor Area"])
        if v is not None:
            m.set("gross_floor_area", v, "quantity")
        else:
            v, src = bag.find_property(["GrossFloorArea", "Gross Floor Area"])
            if v is not None:
                m.set("gross_floor_area", v, "property")
        # perimeter
        v, src = bag.find_quantity(["NetPerimeter", "GrossPerimeter", "Perimeter"])
        if v is not None:
            m.set("perimeter", v, "quantity")
        else:
            v, src = bag.find_property(["Perimeter", "NetPerimeter"])
            if v is not None:
                m.set("perimeter", v, "property")
            elif g_per:
                m.set("perimeter", g_per, "geometry")
        # floor / ceiling z + height ----------------------------------------------------------------------
        g_floor = g_ceil = None
        if pg is not None:
            g_floor, g_ceil = float(pg.verts[:, 2].min()), float(pg.verts[:, 2].max())
            m.set("floor_z", g_floor, "geometry")
            m.set("ceiling_z", g_ceil, "geometry")
            m.set("geometry_height", g_ceil - g_floor, "geometry")
            if poly is not None:
                hmin, hmean = self.ceiling_profile(pg, poly, g_floor)
                if hmin is not None:
                    m.set("height_min", hmin, "geometry")
                    m.set("height_mean", hmean, "geometry")
                    m.v["ceiling_sloped"] = bool((g_ceil - g_floor) - hmin > 0.15)
        elif st is not None:
            m.set("floor_z", st["elevation"], "inferred")
        h_q, _ = bag.find_quantity(["ClearHeight", "NetHeight", "Clear Height"])
        if h_q is None:
            fc, _ = bag.find_quantity(["FinishCeilingHeight"])
            ff, _ = bag.find_quantity(["FinishFloorHeight"], positive=False)
            if fc is not None:
                h_q = fc - (ff or 0.0)
                if h_q <= 0:
                    h_q = None
        if h_q is None:
            h_q, _ = bag.find_quantity(["Height", "Unbounded Height"])
        if h_q is not None:
            m.set("height", h_q, "quantity")
        else:
            v, _ = bag.find_property(["ClearHeight", "Clear Height", "NetHeight", "Height", "Unbounded Height", "Raumhöhe", "Raumhoehe"])
            if v is not None:
                m.set("height", v, "property")
            elif g_floor is not None:
                m.set("height", g_ceil - g_floor, "geometry")
        if m.has("height") and m.has("geometry_height") and m.p.get("height") in ("quantity", "property") \
                and abs(m.v["height"] - m.v["geometry_height"]) > 0.2:
            self.warn(f"space '{el.LongName or el.Name}': declared height {m.v['height']:.2f} m but geometry z-extent "
                      f"{m.v['geometry_height']:.2f} m (sloped/stepped ceiling?)", key="space-height")
        if m.has("net_floor_area") and g_area and m.p.get("net_floor_area") in ("quantity", "property"):
            ref = m.v.get("gross_floor_area") or m.v["net_floor_area"]
            if min(abs(m.v["net_floor_area"] - g_area), abs(ref - g_area)) / max(g_area, 0.01) > 0.15:
                self.warn(f"space '{el.LongName or el.Name}': area quantity {m.v['net_floor_area']:.2f} m2 vs geometry "
                          f"footprint {g_area:.2f} m2", key="space-area")
        # usage ------------------------------------------------------------------------------------------------
        usage, usrc, matched = classify_space(el.Name, el.LongName, el.ObjectType, getattr(el, "Description", None), bag)
        m.set("usage", usage, "inferred")
        m.v["usage_source"] = usrc
        ex["usage_match"] = matched
        # anchor
        if poly is not None:
            rp = poly.representative_point() if not poly.contains(poly.centroid) else poly.centroid
            z0 = g_floor if g_floor is not None else (st["elevation"] if st else 0.0)
            hh = m.v.get("height") or 2.5
            e["anchor"] = [_r(rp.x), _r(rp.y), _r(z0 + min(hh, 3.0) / 2.0)]
        m.v["door_guids"] = []
        m.v["window_guids"] = []
        m.v["exterior_wall_guids"] = []
        return m

    def ceiling_profile(self, pg, poly, floor_z):
        """(min, mean) ceiling height above floor over the footprint by sampling the upward-facing top surface."""
        try:
            tri = pg.tri
            n, a = G.triangle_normals(tri)
            top = tri[(n[:, 2] > 0.05) & (tri[:, :, 2].mean(axis=1) > floor_z + 0.3)]
            if not len(top):
                return None, None
            minx, miny, maxx, maxy = poly.bounds
            step = max(0.2, math.sqrt(poly.area) / 25.0)
            xs = np.arange(minx + step / 2, maxx, step)
            ys = np.arange(miny + step / 2, maxy, step)
            gx, gy = np.meshgrid(xs, ys)
            pts = np.column_stack([gx.ravel(), gy.ravel()])
            from shapely import contains_xy
            inside = contains_xy(poly, pts[:, 0], pts[:, 1])
            pts = pts[inside]
            if len(pts) < 3:
                return None, None
            zt = np.full(len(pts), -np.inf)
            for t in top:
                p0, p1, p2 = t
                d = (p1[1] - p2[1]) * (p0[0] - p2[0]) + (p2[0] - p1[0]) * (p0[1] - p2[1])
                if abs(d) < 1e-12:
                    continue
                l1 = ((p1[1] - p2[1]) * (pts[:, 0] - p2[0]) + (p2[0] - p1[0]) * (pts[:, 1] - p2[1])) / d
                l2 = ((p2[1] - p0[1]) * (pts[:, 0] - p2[0]) + (p0[0] - p2[0]) * (pts[:, 1] - p2[1])) / d
                l3 = 1 - l1 - l2
                ok = (l1 >= -1e-9) & (l2 >= -1e-9) & (l3 >= -1e-9)
                z = l1 * p0[2] + l2 * p1[2] + l3 * p2[2]
                zt = np.where(ok, np.maximum(zt, z), zt)
            valid = np.isfinite(zt)
            if valid.sum() < 3:
                return None, None
            h = zt[valid] - floor_z
            return float(h.min()), float(h.mean())
        except Exception:
            return None, None

    # ---- linking ----------------------------------------------------------------------------------------------
    def build_boundaries(self):
        """IfcRelSpaceBoundary index: element step id -> list[(space_step, 'EXTERNAL'|'INTERNAL'|None)]."""
        by_elem = defaultdict(list)
        for rel in self.ifc.by_type("IfcRelSpaceBoundary"):
            sp, el = rel.RelatingSpace, rel.RelatedBuildingElement
            if sp is None or el is None or not sp.is_a("IfcSpace"):
                continue
            ie = getattr(rel, "InternalOrExternalBoundary", None)
            by_elem[el.id()].append((sp.id(), str(ie).upper() if ie else None))
        self.boundaries = by_elem
        return by_elem

    def link_openings(self):
        """Fill space.door_guids/window_guids, door/window space_guids and external flags."""
        spaces = [e for e in self.elements if e["kind"] == "space"]
        space_step = {e["express_id"]: e for e in spaces}
        polys = {sid: self.polys.get(sid) for sid in space_step}
        link = defaultdict(set)           # opening step -> set(space step)
        link_src = {}
        for e in self.elements:
            if e["kind"] not in ("door", "window"):
                continue
            sid = e["express_id"]
            bl = [s for s, _ in self.boundaries.get(sid, []) if s in space_step]
            if bl:
                link[sid] = set(bl)
                link_src[sid] = "boundary"
        # geometric proximity for the rest
        tree_items = [(sid, p) for sid, p in polys.items() if p is not None]
        for e in self.elements:
            if e["kind"] not in ("door", "window") or e["express_id"] in link:
                continue
            res = self.proximity_spaces(e, tree_items, space_step)
            if res:
                link[e["express_id"]] = res
                link_src[e["express_id"]] = "geometry"
        self.opening_link = link
        self.opening_link_src = link_src
        for sid, sps in link.items():
            e = self.by_step[sid]
            guids = sorted(space_step[s]["guid"] for s in sps)
            if e["kind"] == "door":
                e["measures"]["space_guids"] = guids
                e["provenance"]["space_guids"] = "property" if link_src[sid] == "boundary" else "geometry"
            e["extra"]["space_link"] = link_src[sid]
            if e["kind"] == "window":
                e["measures"]["space_guids"] = guids
                e["provenance"]["space_guids"] = "property" if link_src[sid] == "boundary" else "geometry"
            for s in sps:
                key = "door_guids" if e["kind"] == "door" else "window_guids"
                lst = space_step[s]["measures"][key]
                if e["guid"] not in lst:
                    lst.append(e["guid"])
        for e in self.elements:
            if e["kind"] in ("door", "window") and "space_guids" not in e["measures"]:
                e["measures"]["space_guids"] = []

    def proximity_spaces(self, e, tree_items, space_step):
        pg = self.geoms.get(e["express_id"])
        ri = self.rects.get(e["express_id"])
        if pg is None or ri is None or not tree_items:
            return None
        zmin, zmax = float(pg.verts[:, 2].min()), float(pg.verts[:, 2].max())
        el = self.entity(e)
        wall = self.host_wall(el)
        thick = 0.3
        if wall is not None and wall.id() in self.by_step:
            t = self.by_step[wall.id()]["measures"].get("thickness")
            if t:
                thick = t
        thick = max(thick, ri["short"], 0.1)
        c = ri["center"]
        d = ri["long_dir"]
        nrm = ri["short_dir"]
        half = ri["long"] / 2.0
        axis = LineString([(c[0] - d[0] * half, c[1] - d[1] * half), (c[0] + d[0] * half, c[1] + d[1] * half)])
        thr = thick / 2.0 + 0.2
        cand = {}
        for sid, poly in tree_items:
            sp = space_step[sid]
            fz, cz = sp["measures"].get("floor_z"), sp["measures"].get("ceiling_z")
            if fz is None or cz is None:
                continue
            if not (zmin + 0.05 >= fz - 0.3 and zmin < cz - 0.2):
                continue
            dist = poly.distance(axis)
            if dist > thr:
                continue
            # which side of the opening plane is the space on
            near = poly.exterior.interpolate(poly.exterior.project(Point(c[0], c[1])))
            side = np.sign((near.x - c[0]) * nrm[0] + (near.y - c[1]) * nrm[1]) or 1.0
            if side not in cand or dist < cand[side][0]:
                cand[side] = (dist, sid)
        return {v[1] for v in cand.values()} or None

    # ---- external classification -------------------------------------------------------------------------------
    def classify_walls(self):
        spaces_by_storey = defaultdict(list)
        for e in self.elements:
            if e["kind"] == "space" and self.polys.get(e["express_id"]) is not None:
                spaces_by_storey[e["storey_id"]].append(self.polys[e["express_id"]])
        walls = [e for e in self.elements if e["kind"] == "wall"]
        wall_polys = {e["express_id"]: self.polys.get(e["express_id"]) for e in walls}
        for e in walls:
            sid = e["express_id"]
            el = self.entity(e)
            bag = self.bags[sid]
            m = e["measures"]
            ie, _ = bag.find_bool(["IsExternal"])
            if ie is not None:
                m["is_external"] = ie
                e["provenance"]["is_external"] = "property"
                continue
            bl = self.boundaries.get(sid, [])
            kinds = {k for _, k in bl if k}
            if "EXTERNAL" in kinds:
                m["is_external"] = True
                e["provenance"]["is_external"] = "property"
                continue
            if kinds == {"INTERNAL"}:
                m["is_external"] = False
                e["provenance"]["is_external"] = "property"
                continue
            txt = fold(" ".join(str(x) for x in (el.Name, el.ObjectType) if x))
            if re.search(r"(exterior|extern|aussen|dis duvar|dis cephe|facade|fassade|\bext\b|\bao\b)", txt):
                m["is_external"] = True
                e["provenance"]["is_external"] = "inferred"
                continue
            if re.search(r"(interior|intern|innen|ic duvar|\bint\b|partition|trennwand)", txt):
                m["is_external"] = False
                e["provenance"]["is_external"] = "inferred"
                continue
            res = self.probe_wall(e, spaces_by_storey.get(e["storey_id"], []), wall_polys)
            if res is not None:
                m["is_external"] = res
                e["provenance"]["is_external"] = "geometry"
        # space exterior walls (via boundary or proximity done in finish_spaces)

    def probe_wall(self, e, space_polys, wall_polys):
        ri = self.rects.get(e["express_id"])
        if ri is None or not space_polys:
            return None
        c, d, n = ri["center"], ri["long_dir"], ri["short_dir"]
        t = ri["short"]
        off = t / 2 + 0.2
        ext_votes = int_votes = unknown = 0
        union = None
        for frac in (-0.3, -0.15, 0.0, 0.15, 0.3):
            p = c + d * ri["long"] * frac
            ins = []
            for sgn in (-1, 1):
                q = p + n * off * sgn
                pt = Point(q[0], q[1])
                inside_space = any(sp.contains(pt) for sp in space_polys)
                ins.append(inside_space)
            if ins[0] and ins[1]:
                int_votes += 1
            elif ins[0] != ins[1]:
                ext_votes += 1
            else:
                unknown += 1
        if ext_votes >= 3:
            return True
        if int_votes >= 3:
            return False
        return None

    def finish_openings(self):
        """is_external / is_entrance for doors and windows; space.has_exterior_window etc."""
        lowest_above = next((s for s in self.storeys if not s["is_underground"]), None)
        walls_by_step = {e["express_id"]: e for e in self.elements if e["kind"] == "wall"}
        for e in self.elements:
            if e["kind"] not in ("door", "window"):
                continue
            sid = e["express_id"]
            m, pv = e["measures"], e["provenance"]
            el = self.entity(e)
            if m.get("is_external") is None:
                bl = self.boundaries.get(sid, [])
                kinds = {k for _, k in bl if k}
                if "EXTERNAL" in kinds:
                    m["is_external"], pv["is_external"] = True, "property"
                elif kinds == {"INTERNAL"}:
                    m["is_external"], pv["is_external"] = False, "property"
                else:
                    hw = self.host_wall(el)
                    we = walls_by_step.get(hw.id()) if hw is not None else None
                    if we is not None and we["measures"].get("is_external") is not None:
                        m["is_external"] = we["measures"]["is_external"]
                        pv["is_external"] = "inferred"
                        e["extra"]["host_wall_guid"] = we["guid"]
                    elif e["kind"] == "door" and self.opening_link_src.get(sid) is not None:
                        n = len(self.opening_link.get(sid, ()))
                        if n >= 2:
                            m["is_external"], pv["is_external"] = False, "inferred"
                        elif n == 1:
                            m["is_external"], pv["is_external"] = True, "inferred"
            if e["kind"] == "door":
                ent = None
                if m.get("is_external") is True:
                    st = self.storey_dict(e)
                    on_entry = st is not None and lowest_above is not None and st["id"] == lowest_above["id"]
                    txt = fold(" ".join(str(x) for x in (el.Name, el.ObjectType) if x))
                    if _ENTRANCE_WORDS.search(txt):
                        ent, ep = True, "inferred"
                    elif _TERRACE_WORDS.search(txt):
                        ent, ep = False, "inferred"
                    elif st is not None and lowest_above is not None:
                        ent, ep = on_entry, "inferred"
                    else:
                        ent, ep = None, None
                    m["is_entrance"] = ent
                    if ep:
                        pv["is_entrance"] = ep
                elif m.get("is_external") is False:
                    m["is_entrance"] = False
                    pv["is_entrance"] = "inferred"
                else:
                    m["is_entrance"] = None
        # space aggregates
        by_guid = {e["guid"]: e for e in self.elements}
        for sp in self.elements:
            if sp["kind"] != "space":
                continue
            m, pv = sp["measures"], sp["provenance"]
            wins = [by_guid[g] for g in m["window_guids"]]
            area = 0.0
            known_area = False
            ext_flags = []
            for w in wins:
                a = w["measures"].get("area")
                if a:
                    area += a
                    known_area = True
                ext_flags.append(w["measures"].get("is_external"))
            m["window_area"] = _r(area) if known_area else (0.0 if not wins and self.has_link_data else None)
            if known_area or (not wins and self.has_link_data):
                pv["window_area"] = "geometry" if any(self.opening_link_src.get(w["express_id"]) == "geometry" for w in wins) else "property"
            if wins:
                if any(f is True for f in ext_flags):
                    m["has_exterior_window"], pv["has_exterior_window"] = True, "property"
                elif all(f is False for f in ext_flags):
                    m["has_exterior_window"], pv["has_exterior_window"] = False, "property"
                else:
                    m["has_exterior_window"] = None
            elif self.has_link_data:
                m["has_exterior_window"], pv["has_exterior_window"] = False, "inferred"
            # exterior walls: boundary-based, else proximity
            ext = []
            for step, lst in self.boundaries_by_space.get(sp["express_id"], {}).items():
                we = self.by_step.get(step)
                if we is not None and we["kind"] == "wall" and any(k == "EXTERNAL" for k in lst):
                    ext.append(we["guid"])
            if not ext and sp["express_id"] not in self.spaces_with_boundaries:
                poly = self.polys.get(sp["express_id"])
                if poly is not None:
                    for we in self.elements:
                        if we["kind"] != "wall" or we["storey_id"] != sp["storey_id"] or we["measures"].get("is_external") is not True:
                            continue
                        wp = self.polys.get(we["express_id"])
                        if wp is not None and wp.distance(poly) < 0.25:
                            ext.append(we["guid"])
            m["exterior_wall_guids"] = sorted(set(ext))
            if m["exterior_wall_guids"]:
                pv["exterior_wall_guids"] = "property" if sp["express_id"] in self.spaces_with_boundaries else "geometry"
            m["door_guids"].sort()
            m["window_guids"].sort()

    # ---- driver ---------------------------------------------------------------------------------------------------
    def run(self):
        self.build_storeys()
        products = self.collect_products()
        self.build(products)
        self.build_boundaries()
        self.boundaries_by_space = defaultdict(lambda: defaultdict(list))
        self.spaces_with_boundaries = set()
        for step, lst in self.boundaries.items():
            for sp, k in lst:
                self.boundaries_by_space[sp][step].append(k)
                self.spaces_with_boundaries.add(sp)
        self.has_link_data = False
        # pass 2: measures
        order = ["space", "wall", "slab", "roof", "door", "window", "stair", "railing", "covering"]
        for e in self.elements:
            el = self.entity(e)
            kind = e["kind"]
            try:
                if kind == "space":
                    m = self.measure_space(e, el)
                elif kind == "wall":
                    m = self.measure_wall(e, el)
                elif kind in ("door", "window"):
                    m = self.measure_opening(e, el, kind)
                elif kind == "slab":
                    m = self.measure_slab(e, el)
                elif kind == "roof":
                    m = self.measure_roof(e, el)
                elif kind == "stair":
                    m = self.measure_stair(e, el)
                elif kind == "railing":
                    m = self.measure_railing(e, el)
                elif kind == "covering":
                    m = self.measure_covering(e, el)
                else:
                    m = self.measure_simple(e, el, kind)
            except Exception as ex:  # robustness: never crash on one element
                self.warn(f"{e['ifc_class']} {e['guid']}: measure extraction failed ({type(ex).__name__}: {ex})", key="measure-fail")
                m = Meas()
            e["measures"] = m.v
            e["provenance"] = m.p
        self.has_link_data = bool(self.boundaries) or any(
            self.polys.get(e["express_id"]) is not None for e in self.elements if e["kind"] == "space")
        self.classify_walls()
        self.link_openings()
        self.finish_openings()
        self.post_checks()
        return self

    def post_checks(self):
        n_space = sum(1 for e in self.elements if e["kind"] == "space")
        if n_space == 0:
            self.warnings.append("model contains no IfcSpace: no room-based checks possible")
        cnt = Counter(e["kind"] for e in self.elements)
        for k in ("door", "window", "wall"):
            if cnt[k] == 0:
                self.warnings.append(f"model contains no {k} elements")
        noside = [e for e in self.elements if e["storey_id"] is None]
        if noside and self.storeys:
            self.warn(f"{len(noside)} elements could not be assigned to a storey", key="nostorey")
        for e in self.elements:
            if e["kind"] == "space" and e["measures"].get("footprint") is None:
                self.warn(f"space '{e['name']}' ({e['guid']}) has no usable footprint geometry", key="space-nofp")

    # ---- light index for GLB export --------------------------------------------------------------------------------
    def quick_index(self):
        """{step_id: dict(guid, ifc_class, kind, storey_id, name, parent_guid)} for geometry-bearing products."""
        self.build_storeys()
        products = self.collect_products()
        out = {}
        for el in products:
            if el.id() not in self.geoms:
                continue
            kind = kind_of(el)
            parent = self.parent_of.get(el.id())
            if el.is_a("IfcStairFlight"):
                kind = "other" if (parent is not None and parent.is_a("IfcStair")) else "stair"
            st, _ = self.storey_of(el)
            if st is None and parent is not None:
                st, _ = self.storey_of(parent)
            if st is None and self.storeys:
                pg = self.geoms[el.id()]
                zref = float(pg.verts[:, 2].max()) - 0.01 if kind in ("slab", "roof") else float(pg.verts[:, 2].mean())
                st = self.storey_by_z(zref)
            gp = None
            if parent is not None and parent.is_a("IfcElement") and parent.id() not in self.geoms:
                gp = parent
            out[el.id()] = {"guid": el.GlobalId, "ifc_class": el.is_a(), "kind": kind,
                            "storey_id": st["id"] if st else None, "name": el.Name, "group_parent": gp,
                            "storey": st}
        self._products = products
        return out
