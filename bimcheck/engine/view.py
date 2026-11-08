"""Read-only convenience views over BuildingModel / DrawingModel / ProjectContext dicts."""
from __future__ import annotations

from collections import Counter
from typing import Any

from .util import bbox_center, has_kw, num, poly_area, poly_centroid

CONTENT_KINDS = {"wall", "slab", "space", "door", "window", "stair", "column", "beam", "covering", "railing"}
LIVING_KINDS = {"space", "door", "window", "stair"}
HABITABLE_USAGES = {"living_room", "bedroom", "kitchen", "commercial"}
LIFT_WORDS = ("lift", "asansor", "elevator", "aufzug")


class ModelView:
    """Indexes a BuildingModel dict. Never mutates it."""

    def __init__(self, bm: dict):
        self.raw = bm
        self.storeys: list[dict] = sorted(
            bm.get("storeys") or [],
            key=lambda s: (num(s.get("elevation")) if num(s.get("elevation")) is not None else 0.0))
        self.storey_by_id = {s.get("id"): s for s in self.storeys}
        self.elements: list[dict] = list(bm.get("elements") or [])
        self.by_guid = {e.get("guid"): e for e in self.elements if e.get("guid")}
        self._by_kind: dict[str, list[dict]] = {}
        for e in self.elements:
            self._by_kind.setdefault(e.get("kind") or "other", []).append(e)
        self._fp_cache: dict | None = None
        self._count_cache: dict | None = None

    # ---- generic lookups
    def of_kind(self, kind: str) -> list[dict]:
        return self._by_kind.get(kind, [])

    def storey_of(self, el: dict) -> dict | None:
        return self.storey_by_id.get(el.get("storey_id"))

    def storey_name(self, sid: str | None) -> str | None:
        s = self.storey_by_id.get(sid)
        return (s.get("name") or sid) if s else None

    def elevation(self, sid: str | None) -> float | None:
        s = self.storey_by_id.get(sid)
        return num(s.get("elevation")) if s else None

    @staticmethod
    def name(el: dict) -> str:
        return str(el.get("name") or el.get("long_name") or el.get("object_type") or str(el.get("guid"))[:8])

    @staticmethod
    def measure(el: dict, key: str) -> Any:
        return (el.get("measures") or {}).get(key)

    @staticmethod
    def prov(el: dict, key: str) -> str | None:
        return (el.get("provenance") or {}).get(key)

    def anchor(self, el: dict) -> list[float] | None:
        a = el.get("anchor")
        if a and len(a) >= 3 and all(num(v) is not None for v in a[:3]):
            return [float(v) for v in a[:3]]
        return bbox_center(el.get("bbox"))

    def floor_z(self, el: dict) -> float | None:
        z = num(self.measure(el, "floor_z"))
        if z is not None:
            return z
        e = self.elevation(el.get("storey_id"))
        if e is not None:
            return e
        bb = el.get("bbox")
        return num(bb["min"][2]) if bb else None

    # ---- storeys
    @property
    def above_ground(self) -> list[dict]:
        return [s for s in self.storeys if not s.get("is_underground")]

    @property
    def ground_storey(self) -> dict | None:
        ag = self.above_ground
        return ag[0] if ag else None

    def storey_has_content(self, sid: str) -> bool:
        """A storey counts when it holds rooms or openings/stairs (a level with only a roof, parapet or railing does not)."""
        for e in self.elements:
            if e.get("storey_id") != sid:
                continue
            k = e.get("kind")
            if k in ("door", "stair"):
                return True
            if k == "space" and (e.get("measures") or {}).get("usage") not in (None, "other", "technical"):
                return True
        return False

    def storey_spaces(self, sid: str) -> list[dict]:
        return [e for e in self.of_kind("space") if e.get("storey_id") == sid]

    def storey_kind(self, st: dict) -> str:
        if st.get("is_underground"):
            return "basement"
        ag = self.above_ground
        if ag and st.get("id") == ag[0].get("id"):
            return "ground"
        if ag and st.get("id") == ag[-1].get("id"):
            return "top"
        return "upper"

    def matches_storey_kind(self, st: dict | None, kind: str | None) -> bool:
        if not kind or str(kind).lower() in ("any", "all", "null"):
            return True
        if st is None:
            return False
        k = str(kind).lower()
        sk = self.storey_kind(st)
        if k in ("ground", "ground_floor", "zemin"):
            return sk == "ground"
        if k in ("basement", "underground", "bodrum"):
            return sk == "basement"
        if k in ("upper", "normal", "typical", "other", "upper_floor"):
            return sk in ("upper", "top")
        if k in ("top", "last", "roof_floor"):
            return sk == "top"
        if k in ("above_ground", "aboveground"):
            return sk != "basement"
        if k in ("not_ground", "non_ground"):
            return sk != "ground"
        return True  # unknown vocabulary: do not silently exclude

    def storey_height(self, st: dict) -> float | None:
        """Floor-top to floor-top height: next storey elevation difference, else storey.height."""
        i = self.storeys.index(st)
        e = num(st.get("elevation"))
        if i + 1 < len(self.storeys) and e is not None:
            n = num(self.storeys[i + 1].get("elevation"))
            if n is not None:
                return n - e
        return num(st.get("height"))

    def storey_counts(self) -> dict:
        """Number of storeys relevant to the regulation.

        above  : above-ground storeys that really hold building content (a roof-only level is ignored)
        habitable_basements : underground storeys containing habitable spaces (Madde 34 counts these)
        uncertain_basements : underground storeys with spaces of unclassified usage"""
        if self._count_cache is not None:
            return self._count_cache
        above = [s for s in self.above_ground if self.storey_has_content(s.get("id"))]
        hab, unc = [], []
        for s in self.storeys:
            if not s.get("is_underground"):
                continue
            sp = self.storey_spaces(s.get("id"))
            us = {self.measure(x, "usage") for x in sp}
            if us & HABITABLE_USAGES:
                hab.append(s)
            elif sp and any(u in (None, "other", "hall") for u in us):
                unc.append(s)
        self._count_cache = {"above": len(above), "above_storeys": above, "habitable_basements": len(hab),
                             "uncertain_basements": len(unc), "total": len(above) + len(hab)}
        return self._count_cache

    # ---- lifts
    def lift_evidence(self) -> tuple[str, list[str]]:
        """('element'|'space'|'none', guids)"""
        el, sp = [], []
        for e in self.elements:
            cls = e.get("ifc_class") or ""
            txt = " ".join(str(e.get(k) or "") for k in ("name", "long_name", "object_type"))
            if cls in ("IfcTransportElement", "IfcTransportElementType"):
                el.append(e["guid"])
            elif e.get("kind") == "space":
                if has_kw(txt, LIFT_WORDS):
                    sp.append(e["guid"])
            elif has_kw(txt, LIFT_WORDS) and e.get("kind") in ("other", "door"):
                el.append(e["guid"])
        if el:
            return "element", el
        if sp:
            return "space", sp
        return "none", []

    # ---- footprint / areas
    def footprint(self) -> dict | None:
        """Estimated building footprint polygon: {'geom': shapely, 'area', 'source', 'confidence'}."""
        if self._fp_cache is not None:
            return self._fp_cache or None
        res = self._compute_footprint()
        self._fp_cache = res or {}
        return res

    def _compute_footprint(self) -> dict | None:
        try:
            from shapely.geometry import Polygon, box
            from shapely.ops import unary_union
        except Exception:  # pragma: no cover
            return None
        g = self.ground_storey
        if not g:
            return None
        gid = g.get("id")

        def boxes(kind, pred=None):
            out = []
            for e in self.of_kind(kind):
                if e.get("storey_id") != gid or (pred and not pred(e)):
                    continue
                bb = e.get("bbox")
                if not bb:
                    continue
                out.append(box(bb["min"][0], bb["min"][1], bb["max"][0], bb["max"][1]))
            return out

        slabs = boxes("slab", lambda e: not self.measure(e, "is_roof"))
        walls = boxes("wall")
        spaces = []
        for e in self.storey_spaces(gid):
            fp = self.measure(e, "footprint")
            if fp and len(fp) >= 3:
                try:
                    p = Polygon([(float(x), float(y)) for x, y in fp])
                    if not p.is_valid:
                        p = p.buffer(0)
                    if not p.is_empty:
                        spaces.append(p)
                except Exception:
                    pass
        su = unary_union(spaces).buffer(0.3, join_style=2) if spaces else None
        sl = unary_union(slabs) if slabs else None
        wa = unary_union(walls) if walls else None
        if wa is not None:
            wa = Polygon(wa.exterior) if wa.geom_type == "Polygon" else wa.convex_hull
        sp_src = "ground-floor space footprints +0.30 m"
        if sl is not None and su is not None:
            ratio = sl.area / su.area if su.area > 0 else 99
            if ratio <= 1.10:
                return {"geom": sl, "area": sl.area, "source": "ground slab bounding boxes", "confidence": "geometry"}
            return {"geom": su, "area": su.area, "source": sp_src + " (slab boxes too large - rotated plan?)",
                    "confidence": "inferred"}
        if sl is not None:
            return {"geom": sl, "area": sl.area, "source": "ground slab bounding boxes", "confidence": "geometry"}
        if wa is not None and su is not None and wa.area / max(su.area, 1e-9) > 1.35:
            return {"geom": su, "area": su.area, "source": sp_src, "confidence": "inferred"}
        if wa is not None:
            return {"geom": wa, "area": wa.area, "source": "ground wall bounding boxes", "confidence": "geometry"}
        if su is not None:
            return {"geom": su, "area": su.area, "source": sp_src, "confidence": "inferred"}
        return None

    def storey_floor_area(self, st: dict) -> tuple[float | None, str]:
        """Approximate gross floor area of a storey (overlapping slab layers / outside terraces are NOT summed).

        Preferred: union of the room footprints grown by 0.30 m (wall half-thickness); fallback: union of the
        floor-slab bounding boxes; last resort: sum of space areas."""
        sid = st.get("id")
        try:
            from shapely.geometry import Polygon, box
            from shapely.ops import unary_union
        except Exception:  # pragma: no cover
            return None, "none"
        polys = []
        for e in self.storey_spaces(sid):
            fp = self.measure(e, "footprint")
            if fp and len(fp) >= 3:
                try:
                    p = Polygon([(float(x), float(y)) for x, y in fp])
                    p = p if p.is_valid else p.buffer(0)
                    if not p.is_empty:
                        polys.append(p)
                except Exception:
                    pass
        if polys:
            return unary_union(polys).buffer(0.3, join_style=2).area, "room footprints + 0.30 m walls"
        boxes = []
        for e in self.of_kind("slab"):
            if e.get("storey_id") == sid and not self.measure(e, "is_roof") and e.get("bbox"):
                bb = e["bbox"]
                boxes.append(box(bb["min"][0], bb["min"][1], bb["max"][0], bb["max"][1]))
        if boxes:
            return unary_union(boxes).area, "floor slab outlines"
        tot, n = 0.0, 0
        for e in self.storey_spaces(sid):
            a = num(self.measure(e, "gross_floor_area"))
            if a is None:
                a = num(self.measure(e, "net_floor_area"))
            if a is not None:
                tot += a
                n += 1
        return (tot, "space areas") if n else (None, "none")


class DrawingView:
    def __init__(self, dm: dict):
        self.raw = dm
        self.rooms: list[dict] = list(dm.get("rooms") or [])
        self.views = {v.get("id"): v for v in (dm.get("views") or [])}
        self.parcel = dm.get("parcel") or None
        self.footprint = dm.get("footprint") or None

    def view_name(self, vid: str | None) -> str | None:
        v = self.views.get(vid)
        return v.get("name") if v else None

    def floor_plan_count(self) -> int:
        return sum(1 for v in self.views.values() if v.get("kind") == "floor_plan")

    def room_as_space(self, r: dict) -> dict:
        """A drawing room dressed as a BuildingModel 'space' element (guid prefixed 'dm:')."""
        poly = r.get("polygon") or []
        area = num(r.get("area"))
        if area is None:
            area = poly_area(poly)
        lp = r.get("label_point")
        if lp is None and len(poly) >= 3:
            lp = list(poly_centroid(poly))
        v = self.views.get(r.get("view_id")) or {}
        lvl = num(v.get("elevation"))
        z = lvl if lvl is not None else 0.0
        return {
            "guid": f"dm:{r.get('id')}", "ifc_class": None, "kind": "space", "name": r.get("name"),
            "storey_id": None, "bbox": None,
            "anchor": [lp[0], lp[1], z] if lp else None,
            "props": {},
            "provenance": {k: ("geometry" if (num(r.get("confidence")) or 0) >= 0.5 else "inferred")
                           for k in ("net_floor_area", "gross_floor_area", "min_width", "footprint")},
            "measures": {"net_floor_area": area, "gross_floor_area": area, "min_width": num(r.get("min_width")),
                         "usage": r.get("usage"), "footprint": poly, "floor_z": lvl,
                         "height": None, "has_exterior_window": None},
            "_dm_room": r, "_view_id": r.get("view_id"),
        }


def dm_room_doubt(el: dict) -> str | None:
    """Why a drawing-derived room geometry cannot be trusted for a hard verdict (None = trustworthy)."""
    r = el.get("_dm_room")
    if not r:
        return None
    conf = num(r.get("confidence"))
    if conf is not None and conf < 0.7:
        return f"the room outline was detected with low confidence ({conf:.2f})"
    area, lab = num(r.get("area")), num(r.get("labelled_area"))
    if area and lab and abs(area - lab) > max(0.5, 0.1 * lab):
        return f"computed area {area:.2f} m2 differs from the labelled area {lab:.2f} m2"
    return None


def effective_use(ctx: dict, bm: ModelView | None, dm: DrawingView | None) -> tuple[str | None, bool]:
    """(use, inferred?) - context.use wins, else inferred from space usages."""
    u = ctx.get("use")
    if u:
        return str(u), False
    cnt: Counter = Counter()  # net area per usage
    if bm:
        for sp in bm.of_kind("space"):
            cnt[bm.measure(sp, "usage")] += num(bm.measure(sp, "net_floor_area")) or 1.0
    elif dm:
        for r in dm.rooms:
            cnt[r.get("usage")] += num(r.get("area")) or 1.0
    res = cnt["living_room"] + cnt["bedroom"]
    com = cnt["commercial"]
    if res and com and com / (res + com) >= 0.15:  # a single home-office room does not make a house "mixed"
        return "mixed", True
    if res and com:
        return "residential", True
    if res:
        return "residential", True
    if com:
        return "commercial", True
    return None, True


def parcel_info(ctx: dict, dm: DrawingView | None) -> dict:
    """Resolve parcel polygon / area from context first, then drawing model.

    returns {polygon|None, area|None, source:'context'|'drawing_model'|None, view_id|None}"""
    poly = ctx.get("parcel_polygon")
    area = num(ctx.get("parcel_area"))
    if poly and len(poly) >= 3:
        return {"polygon": poly, "area": area if area is not None else poly_area(poly),
                "source": "context", "view_id": None}
    if dm and dm.parcel and dm.parcel.get("polygon"):
        pa = num(dm.parcel.get("area"))
        pp = dm.parcel["polygon"]
        return {"polygon": pp, "area": area if area is not None else (pa if pa is not None else poly_area(pp)),
                "source": "drawing_model", "view_id": dm.parcel.get("view_id")}
    return {"polygon": None, "area": area, "source": "context" if area is not None else None, "view_id": None}


USAGE_EN = {
    "living_room": "Living room", "bedroom": "Bedroom", "kitchen": "Kitchen", "bathroom": "Bathroom", "wc": "WC",
    "corridor": "Corridor", "hall": "Hall", "stair": "Stair room", "storage": "Storage", "balcony": "Balcony",
    "terrace": "Terrace", "technical": "Technical room", "garage": "Garage", "commercial": "Commercial space",
    "other": "Space",
}
USAGE_TR = {
    "living_room": "Oturma odası", "bedroom": "Yatak odası", "kitchen": "Mutfak", "bathroom": "Banyo", "wc": "Tuvalet",
    "corridor": "Koridor", "hall": "Hol", "stair": "Merdiven evi", "storage": "Depo", "balcony": "Balkon",
    "terrace": "Teras", "technical": "Teknik oda", "garage": "Garaj", "commercial": "Ticari alan", "other": "Mekân",
}
KIND_EN = {"space": "Space", "door": "Door", "window": "Window", "stair": "Stair", "railing": "Railing", "wall": "Wall",
           "slab": "Slab", "roof": "Roof", "covering": "Covering", "column": "Column", "beam": "Beam", "other": "Element"}
KIND_TR = {"space": "Mekân", "door": "Kapı", "window": "Pencere", "stair": "Merdiven", "railing": "Korkuluk",
           "wall": "Duvar", "slab": "Döşeme", "roof": "Çatı", "covering": "Kaplama", "column": "Kolon", "beam": "Kiriş",
           "other": "Eleman"}
