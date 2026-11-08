"""Site / zoning checks: parcel setbacks (Madde 23), TAKS/KAKS (Madde 20-22), max storeys (Madde 25),
parcel dimensions (Madde 6)."""
from __future__ import annotations

import math

from ..finding import Env, M, R
from ..judge import Verdict, judge
from ..util import dim, fmt, has_kw, min_rect, num, poly_area
from ..view import ModelView, parcel_info
from . import register
from .common import model_center

NEAR_M = 30.0  # footprint must lie within this distance of the parcel to be considered in the same CRS


# ----------------------------------------------------------------------------- shared helpers
def _open_poly(poly):
    pts = [(float(p[0]), float(p[1])) for p in poly]
    if len(pts) > 1 and pts[0] == pts[-1]:
        pts = pts[:-1]
    return pts


def _storeys_for_zoning(env: Env) -> tuple[int | None, str]:
    """(count, source) - storey count for setback increments / parcel width classes."""
    if env.bm:
        c = env.bm.storey_counts()
        if c["above"]:
            return c["above"], "building_model"
    n = num(env.ctx.get("max_storeys"))
    if n is not None:
        return int(n), "context"
    if env.dm and env.dm.floor_plan_count():
        return env.dm.floor_plan_count(), "drawing_model"
    return None, "unknown"


def _plan_storeys_first(env: Env) -> tuple[int | None, str]:
    n = num(env.ctx.get("max_storeys"))
    if n is not None:
        return int(n), "context"
    return _storeys_for_zoning(env)


def footprint_candidates(env: Env, parcel_geom, parcel_source: str | None) -> list[dict]:
    from shapely.geometry import Polygon
    cands: list[dict] = []
    if env.bm:
        fp = env.bm.footprint()
        if fp:
            cands.append({"geom": fp["geom"], "source": "building_model", "label": fp["source"], "conf": fp["confidence"],
                          "view_id": None})
    dmf = env.dm.footprint if env.dm else None
    if dmf and dmf.get("polygon") and len(dmf["polygon"]) >= 3:
        try:
            g = Polygon(_open_poly(dmf["polygon"]))
            if not g.is_valid:
                g = g.buffer(0)
            if not g.is_empty:
                cands.append({"geom": g, "source": "drawing_model", "label": "drawing footprint", "conf": "geometry",
                              "view_id": dmf.get("view_id")})
        except Exception:
            pass
    if parcel_geom is not None:
        for c in cands:
            c["near"] = parcel_geom.buffer(NEAR_M).intersects(c["geom"])
    else:
        for c in cands:
            c["near"] = True
    if parcel_source == "drawing_model":
        cands.sort(key=lambda c: 0 if c["source"] == "drawing_model" else 1)
    return cands


def _parcel_or_review(env: Env, key: str, what: str):
    pi = parcel_info(env.ctx, env.dm)
    if not pi["polygon"]:
        return pi, [env.review(key, "missing_context",
                               f"Provide the parcel polygon (parcel_polygon in the project context) or a drawing with a parcel layer to evaluate {what}.",
                               f"Parcel polygon not available - {what} cannot be evaluated",
                               f"Parsel poligonu yok - {what} değerlendirilemedi", source="parcel_context")]
    return pi, None


def _shape_parcel(pi):
    from shapely.geometry import Polygon
    g = Polygon(_open_poly(pi["polygon"]))
    if not g.is_valid:
        g = g.buffer(0)
    return g


def classify_edges(poly, front_idx, road_idx=None):
    """List of dict(i, p, q, cls) with cls in front|rear|side|unknown."""
    pts = _open_poly(poly)
    n = len(pts)
    edges = [{"i": i, "p": pts[i], "q": pts[(i + 1) % n], "cls": "unknown"} for i in range(n)]
    if front_idx is None:
        return edges
    fi = int(front_idx) % n
    fronts = {fi} | {int(i) % n for i in (road_idx or [])}
    for e in edges:
        e["cls"] = "front" if e["i"] in fronts else "side"
    fe = edges[fi]
    fmid = ((fe["p"][0] + fe["q"][0]) / 2, (fe["p"][1] + fe["q"][1]) / 2)
    fdir = (fe["q"][0] - fe["p"][0], fe["q"][1] - fe["p"][1])
    fl = math.hypot(*fdir) or 1.0
    best, bd = None, -1.0
    for e in edges:
        if e["i"] in fronts or e["p"] in (fe["p"], fe["q"]) or e["q"] in (fe["p"], fe["q"]):
            continue
        d = (e["q"][0] - e["p"][0], e["q"][1] - e["p"][1])
        dl = math.hypot(*d) or 1.0
        cos = abs((d[0] * fdir[0] + d[1] * fdir[1]) / (dl * fl))
        if cos < 0.7:
            continue
        m = ((e["p"][0] + e["q"][0]) / 2, (e["p"][1] + e["q"][1]) / 2)
        dist = math.hypot(m[0] - fmid[0], m[1] - fmid[1])
        if dist > bd:
            best, bd = e, dist
    if best is not None:
        best["cls"] = "rear"
    return edges


# ----------------------------------------------------------------------------- parcel_setbacks
def setback_requirements(env: Env, n: int | None) -> dict:
    ctx = env.ctx
    extra = 0.5 * max(0, (n if n is not None else 4) - 4)
    out = {}
    for cls, dflt, key in (("front", 5.0, "front_setback"), ("side", 3.0, "side_setback"), ("rear", 3.0, "rear_setback")):
        ov = num(env.override.get(cls))
        plan = num(ctx.get(key))
        if ov is not None:
            out[cls] = (ov, "project override")
        elif plan is not None:
            out[cls] = (plan, "plan note")
        elif cls == "front":
            out[cls] = (dflt, "Madde 23(1)a default")
        else:
            val = dflt + extra
            note = "Madde 23(1)b/c default" + (f" + 0.50 m x {int(extra / 0.5)} storey(s) above 4 (Madde 23(1)ç)" if extra else "")
            out[cls] = (val, note)
    return out


@register("parcel_setbacks")
def parcel_setbacks(env: Env) -> list[dict]:
    from shapely.geometry import LineString
    from shapely.ops import nearest_points
    part, want = env.params.get("part"), env.params.get("edge")
    if part == "storey_increment":
        return [env.na("Included in the side/rear setback rules (+0.50 m per storey above 4, Madde 23(1)ç)",
                       "Yan/arka bahçe kurallarına dahil edildi (4 katın üzerindeki her kat için +0.50 m)")]
    if part == "high_rise":
        bm = env.bm
        h = None
        if bm and bm.ground_storey:
            tops = [e["bbox"]["max"][2] for e in bm.elements if e.get("bbox")]
            h = (max(tops) - (num(bm.ground_storey.get("elevation")) or 0.0)) if tops else None
        if h is not None and h < 60.5:
            return [env.na(f"Building height {h:.1f} m is below 60.50 m: high-rise setbacks do not apply",
                           f"Bina yüksekliği {h:.1f} m < 60.50 m: yüksek yapı mesafeleri uygulanmaz")]
        return [env.review("parcel", "legal_judgement", "Check high-rise setbacks (15 m + 0.50 m per storey above 60.50 m).",
                           "Building height unknown or >= 60.50 m: high-rise setback rule (Madde 23(1)g) needs manual check",
                           "Yüksek yapı bahçe mesafesi (Madde 23(1)g) elle kontrol edilmeli")]
    if part == "between_buildings":
        return [env.na("Distance between several buildings on one parcel is not evaluated (single building model)",
                       "Aynı parseldeki birden fazla bina arası mesafe değerlendirilmedi")]
    pi, rev = _parcel_or_review(env, "parcel", "building setbacks (bahçe mesafeleri)")
    if rev:
        return rev
    parcel = _shape_parcel(pi)
    cands = footprint_candidates(env, parcel, pi["source"])
    if not cands:
        return [env.review("parcel", "missing_measure",
                           "No building footprint could be derived (no IFC ground-storey slabs/walls/spaces and no drawing footprint).",
                           "Building footprint unavailable - setbacks cannot be measured",
                           "Bina oturumu belirlenemedi - bahçe mesafeleri ölçülemedi", source="parcel_context")]
    near = [c for c in cands if c["near"]]
    if not near:
        c = cands[0]
        d = parcel.distance(c["geom"])
        return [env.review("parcel", "missing_context",
                           "The building footprint and the parcel polygon are in different coordinate systems "
                           f"(gap {d:.0f} m). Give the parcel polygon in the model's coordinates or georeference the model.",
                           f"Building footprint lies {d:.0f} m away from the parcel polygon - coordinate systems differ",
                           f"Bina oturumu parsel poligonundan {d:.0f} m uzakta - koordinat sistemleri farklı",
                           source="parcel_context")]
    prim = near[0]
    sec = near[1] if len(near) > 1 else None
    n, nsrc = _storeys_for_zoning(env)
    reqs = setback_requirements(env, n)
    front_idx = env.ctx.get("front_edge_index")
    edges = classify_edges(pi["polygon"], front_idx, env.ctx.get("road_edge_indices"))
    order = (env.ctx.get("building_order") or "").lower()
    tol = env.tol(0.01)
    src = prim["source"]
    view_id = pi["view_id"] if src == "drawing_model" else None
    if src == "building_model" and env.bm and env.bm.ground_storey:
        z = num(env.bm.ground_storey.get("elevation")) or 0.0
    else:
        z = 0.0
    out = []
    min_req = min(reqs["side"][0], reqs["rear"][0])
    max_req = max(reqs["front"][0], reqs["side"][0], reqs["rear"][0])
    for e in edges:
        line = LineString([e["p"], e["q"]])
        if line.length < 0.3:
            continue
        if want:  # rule is specific to one boundary class
            if e["cls"] == "unknown":
                if want != "front":
                    continue  # unclassified edges are reported once, under the front-setback rule
            elif e["cls"] != want:
                continue
        d = prim["geom"].distance(line)
        pa, pb = nearest_points(prim["geom"], line)
        dl = [dim([pa.x, pa.y, z], [pb.x, pb.y, z], fmt(d, "m"), "linear")]
        d2 = sec["geom"].distance(line) if sec else None
        cls = e["cls"]
        key = f"parcel:e{e['i']}"
        prov = prim["conf"]
        kw = dict(tol=tol, prov=prov, min_prov="property", semi=env.semi, legal=env.legal, label="setback distance")
        if cls in ("front", "side", "rear"):
            req, basis = reqs[cls]
            v = judge(d, ">=", req, **kw)
            if cls == "side" and order in ("adjacent", "block") and v.status != "pass":
                v = Verdict("review", "missing_context",
                            f"Building order is '{order}' (bitişik/blok): a side boundary shared with a neighbour may legitimately be at 0 m. "
                            "Confirm which side boundaries are attached.", False)
            label = {"front": "front", "side": "side", "rear": "rear"}[cls]
            en = f"Distance to {label} boundary (parcel edge {e['i']}) is {fmt(d, 'm')}; minimum {fmt(req, 'm')} ({basis})"
            tr = (f"{ {'front': 'Ön', 'side': 'Yan', 'rear': 'Arka'}[cls] } bahçe mesafesi (parsel kenarı {e['i']}) {fmt(d, 'm')}; "
                  f"en az {fmt(req, 'm')}")
            required = R(">=", req, "m")
        else:  # classification unknown: decide only when it is true for every class
            if d >= max_req - tol:
                v = Verdict("pass", ok=True)
            elif d < min_req - tol:
                v = Verdict("violation", ok=False)
            else:
                v = Verdict("review", "missing_context",
                            "Set front_edge_index (the parcel edge facing the road) in the project context: the required setback is "
                            f"{fmt(min_req, 'm')} (side/rear) or {fmt(reqs['front'][0], 'm')} (front) depending on the edge.", None)
            req = max_req if v.status != "violation" else min_req
            en = (f"Distance to parcel edge {e['i']} is {fmt(d, 'm')}; required {fmt(min_req, 'm')} - {fmt(max_req, 'm')} "
                  "depending on whether it is a front, side or rear boundary")
            tr = f"Parsel kenarı {e['i']} mesafesi {fmt(d, 'm')}; gereken {fmt(min_req, 'm')} - {fmt(max_req, 'm')} (ön/yan/arka)"
            required = R(">=", req, "m")
        if sec is not None and d2 is not None and v.status in ("pass", "violation") and abs(d2 - d) > 0.5:
            comp = judge(d2, ">=", req if cls != "unknown" else min_req, **kw)
            if comp.status != v.status and comp.status in ("pass", "violation"):
                v = Verdict("review", "low_confidence",
                            f"IFC footprint gives {fmt(d if src == 'building_model' else d2, 'm')} but the drawing footprint gives "
                            f"{fmt(d2 if src == 'building_model' else d, 'm')}; the two sources disagree - reconcile them.", False)
        if nsrc in ("unknown",) and v.status == "pass" and cls in ("side", "rear"):
            v = Verdict("review", "missing_context", "Storey count unknown: side/rear setbacks grow by 0.50 m per storey above 4.", True)
        out.append(env.from_verdict(
            v, key, en, tr, measured=M(d, "m", prov), required=required, dimensions=dl,
            elements=[],
            storey_id=(env.bm.ground_storey["id"] if src == "building_model" and env.bm and env.bm.ground_storey else None),
            anchor=[pa.x, pa.y, z], source=src if src == "drawing_model" else "parcel_context", view_id=view_id,
            extra={"edge_index": e["i"], "edge_class": cls, "footprint_source": prim["label"], "storeys": n,
                   "storeys_source": nsrc}))
    if not out:
        return [env.na(f"No {want or ''} boundary identified on the parcel polygon", f"Parselde {want or ''} sınır belirlenemedi")]
    return out


# ----------------------------------------------------------------------------- taks_kaks
def _which(env: Env) -> list[str]:
    w = env.params.get("which") or env.params.get("part")
    if w in ("taks", "kaks"):
        return [w]
    if w == "kaks_derived":
        return ["kaks"]
    t = f"{env.rule.get('title_en') or ''} {env.rule.get('title_tr') or ''} {env.rule.get('id') or ''}"
    low = t.lower()
    has_t = "taks" in low or "taban alan" in low or "ground coverage" in low or "footprint" in low
    has_k = "kaks" in low or "emsal" in low or "floor area ratio" in low or "total floor" in low
    if has_t and not has_k:
        return ["taks"]
    if has_k and not has_t:
        return ["kaks"]
    return ["taks", "kaks"]


def _floor_area_total(env: Env):
    """(total_area|None, note, per_storey, lower_bound_only)"""
    bm = env.bm
    if bm:
        counts = bm.storey_counts()
        per = {}
        tot = 0.0
        src = set()
        use = list(counts["above_storeys"])
        for s in bm.storeys:
            if s.get("is_underground"):
                sp = bm.storey_spaces(s["id"])
                if {bm.measure(x, "usage") for x in sp} & {"living_room", "bedroom", "kitchen", "commercial"}:
                    use.append(s)
        for s in use:
            a, how = bm.storey_floor_area(s)
            if a is not None:
                per[s.get("name") or s["id"]] = round(a, 2)
                tot += a
                src.add(how)
        if per:
            note = "from " + " / ".join(sorted(src))
            if counts["uncertain_basements"]:
                note += "; basements with unclassified spaces were not counted"
            return tot, note, per, False
    if env.dm and env.dm.rooms:
        fps = {r.get("view_id") for r in env.dm.rooms}
        tot = sum(num(r.get("area")) or 0.0 for r in env.dm.rooms)
        return tot, "sum of net room areas in the drawing (walls and stairs not included)", {}, True
    return None, "no floor data", {}, False


@register("taks_kaks")
def taks_kaks(env: Env) -> list[dict]:
    which = _which(env)
    pi = parcel_info(env.ctx, env.dm)
    parcel_area = pi["area"]
    out = []
    parcel_geom = _shape_parcel(pi) if pi["polygon"] else None
    for w in which:
        key = f"parcel:{w}" if len(which) > 1 else "parcel"
        name = w.upper()
        ov = num(env.override.get(w))
        lim = ov if ov is not None else num(env.ctx.get(w))
        derivable = num(env.ctx.get("taks")) is not None and num(env.ctx.get("max_storeys")) is not None
        if w == "kaks" and ov is None:
            part = env.params.get("part")
            if part == "kaks_derived":
                if lim is not None or not derivable:
                    return [env.na("KAKS is given directly (or cannot be derived): derived-KAKS rule not used",
                                   "KAKS doğrudan verilmiş (veya türetilemiyor)")]
                lim = float(env.ctx["taks"]) * float(env.ctx["max_storeys"])
            elif part == "kaks" and lim is None and derivable:
                return [env.na("KAKS not given; evaluated by KBB-21-4 as TAKS x storeys", "KAKS verilmemiş; KBB-21-4 ile TAKS x kat adedi olarak değerlendirildi")]
        if lim is None and len(which) == 1:
            lim = env.limit("limit")
        if lim is None:
            out.append(env.review(key, "missing_context", f"Enter the plan's {name} value in the project context ({w}).",
                                  f"{name} limit not given - not evaluated", f"{name} değeri girilmedi - değerlendirilmedi",
                                  source="parcel_context"))
            continue
        if parcel_area is None or parcel_area <= 0:
            out.append(env.review(key, "missing_context", "Provide parcel_area / parcel_polygon (or a drawing with a parcel layer).",
                                  f"Parcel area unknown - {name} cannot be evaluated",
                                  f"Parsel alanı bilinmiyor - {name} değerlendirilemedi", source="parcel_context"))
            continue
        if w == "taks":
            cands = footprint_candidates(env, parcel_geom, pi["source"])
            cands = [c for c in cands if c["near"]] or cands  # area does not depend on CRS
            if not cands:
                out.append(env.review(key, "missing_measure", "No footprint available (IFC ground storey slabs/walls or drawing footprint).",
                                      "Building footprint unavailable - TAKS cannot be evaluated",
                                      "Bina oturumu belirlenemedi - TAKS değerlendirilemedi", source="parcel_context"))
                continue
            c = cands[0]
            fa = c["geom"].area
            ratio = fa / parcel_area
            v = judge(ratio, "<=", lim, tol=env.tol(0.0005) if env.tolerance is None else env.tol(0), prov=c["conf"], min_prov="property",
                      semi=env.semi, legal=env.legal, label="TAKS")
            hint_extra = ""
            if len(cands) > 1:
                fa2 = cands[1]["geom"].area
                if abs(fa2 - fa) > 0.1 * fa:
                    r2 = fa2 / parcel_area
                    ok2 = r2 <= lim + 0.0005
                    if ok2 != (v.status == "pass") and v.status in ("pass", "violation"):
                        v = Verdict("review", "low_confidence",
                                    f"IFC footprint ({fa:.1f} m²) and drawing footprint ({fa2:.1f} m²) lead to different verdicts - reconcile.",
                                    False)
            en = (f"TAKS = footprint {fmt(fa, 'm²', 1)} / parcel {fmt(parcel_area, 'm²', 1)} = {ratio:.3f}; maximum {lim:.2f} "
                  f"(footprint: {c['label']}; approximate)")
            tr = f"TAKS = oturum {fmt(fa, 'm²', 1)} / parsel {fmt(parcel_area, 'm²', 1)} = {ratio:.3f}; en fazla {lim:.2f}"
            z = 0.0
            dl = []
            minx, miny, maxx, maxy = c["geom"].bounds
            if c["source"] == "building_model" and env.bm and env.bm.ground_storey:
                z = num(env.bm.ground_storey.get("elevation")) or 0.0
            dl = [dim([minx, miny, z], [maxx, maxy, z], f"footprint {fmt(fa, 'm²', 1)}", "area")]
            cx, cy = c["geom"].centroid.x, c["geom"].centroid.y
            out.append(env.from_verdict(v, key, en, tr, measured=M(ratio, "", c["conf"]), required=R("<=", lim, ""),
                                        dimensions=dl, anchor=[cx, cy, z], source="parcel_context",
                                        view_id=c["view_id"],
                                        extra={"footprint_area": round(fa, 3), "parcel_area": round(parcel_area, 3),
                                               "footprint_source": c["label"]}))
        else:
            tot, note, per, lower = _floor_area_total(env)
            if tot is None:
                out.append(env.review(key, "missing_measure", "No floor areas could be derived from the model.",
                                      "Floor areas unavailable - KAKS cannot be evaluated",
                                      "Kat alanları bulunamadı - KAKS değerlendirilemedi", source="parcel_context"))
                continue
            ratio = tot / parcel_area
            if lower:
                v = Verdict("review", "low_confidence",
                            ("Net room areas summed from the drawing already EXCEED the limit (lower bound, but rooms may be counted "
                             "twice across drawing views) - " if ratio > lim + 0.0005 else
                             "Only net room areas from the drawing are available (lower bound): walls, stairs and shafts add to "
                             "the KAKS floor area - ") + "compute from the architect's area table.", None)
            else:
                v = judge(ratio, "<=", lim, tol=env.tol(0.0005) if env.tolerance is None else env.tol(0), prov="geometry",
                          min_prov="property", semi=env.semi, legal=env.legal, label="KAKS")
            en = (f"KAKS = total floor area {fmt(tot, 'm²', 1)} / parcel {fmt(parcel_area, 'm²', 1)} = {ratio:.3f}; maximum {lim:.2f} "
                  f"(approximate, Madde 21/22 exclusions not applied; {note})")
            tr = f"KAKS (emsal) = toplam inşaat alanı {fmt(tot, 'm²', 1)} / parsel {fmt(parcel_area, 'm²', 1)} = {ratio:.3f}; en fazla {lim:.2f}"
            c = model_center(env.bm) if env.bm else None
            out.append(env.from_verdict(v, key, en, tr, measured=M(ratio, "", "geometry"), required=R("<=", lim, ""),
                                        anchor=c, source="parcel_context",
                                        extra={"total_floor_area": round(tot, 3), "parcel_area": round(parcel_area, 3),
                                               "per_storey": per, "approximate": True}))
    return out


# ----------------------------------------------------------------------------- max_storeys
@register("max_storeys")
def max_storeys(env: Env) -> list[dict]:
    ov = env.limit("limit") if env.overridden("limit") else None
    lim = ov if ov is not None else num(env.ctx.get("max_storeys"))
    table_note = ""
    if lim is None and env.params.get("table") and num(env.ctx.get("max_height")) is None:
        rw = num(env.ctx.get("road_width"))
        if rw is None:
            return [env.review("model", "missing_context", "Enter road_width (and the plan's storey count if the plan states one).",
                               "Plan storey count and road width unknown - storey limit cannot be selected",
                               "Plan kat adedi ve yol genişliği bilinmiyor", source="parcel_context")]
        for row in env.params["table"]:
            if row.get("road_width_max") is None or rw <= row["road_width_max"]:
                lim = float(row["max_storeys"])
                table_note = f" (road width {rw:g} m, table of Madde 9, applies only to plans before 1/10/2017 that state no storeys)"
                break
    if lim is None:
        return [env.review("model", "missing_context", "Enter the plan's maximum storey count (max_storeys) in the project context.",
                           "Maximum storey count not given - not evaluated", "Azami kat adedi girilmedi - değerlendirilmedi",
                           source="parcel_context")]
    if env.bm:
        c = env.bm.storey_counts()
        n, prov = c["above"], "geometry"
        top = c["above_storeys"][-1] if c["above_storeys"] else None
    elif env.dm and env.dm.floor_plan_count():
        n, prov, top, c = env.dm.floor_plan_count(), "inferred", None, {"habitable_basements": 0}
    else:
        return [env.review("model", "missing_measure", "No storeys could be derived from the model.", "Storey count unavailable",
                           "Kat adedi bulunamadı", source="parcel_context")]
    bm = env.bm
    anchor, dl = None, []
    if bm:
        cc = model_center(bm)
        g = bm.ground_storey
        z0 = num(g.get("elevation")) if g else 0.0
        z1 = num(top.get("elevation")) if top else z0
        if cc:
            anchor = [cc[0], cc[1], z0 or 0.0]
            dl = [dim([cc[0], cc[1], z0 or 0.0], [cc[0], cc[1], max(z1 or 0.0, (z0 or 0.0) + 0.01)], f"{n} storeys", "linear")]
    v = judge(n, "<=", lim, tol=0.0, prov=prov, semi=False, label="storey count")
    hint = None
    if v.status == "violation" and top is not None and bm:
        prev = c["above_storeys"][-2] if len(c["above_storeys"]) > 1 else None
        a_top, _ = bm.storey_floor_area(top)
        a_prev, _ = bm.storey_floor_area(prev) if prev else (None, "")
        attic = has_kw(top.get("name"), ("roof", "cati", "attic", "dach", "teras"))
        small = a_top is not None and a_prev and a_top < 0.5 * a_prev
        if n - lim <= 1 and (attic or small):
            v = Verdict("review", "legal_judgement",
                        "The extra top storey looks like an attic / set-back floor; whether it counts as a storey (kat adedi) "
                        "depends on Madde 21/22/25 - check the section.", False)
    elif v.status == "pass" and n == int(lim) and c.get("habitable_basements"):
        v = Verdict("review", "low_confidence",
                    "Habitable basement storeys exist: if they are partly above natural ground they count towards the storey limit.", True)
    en = f"Building has {n} storey(s) above ground; maximum is {int(lim)}{table_note}"
    tr = f"Binada zemin üstü {n} kat var; planda izin verilen azami kat adedi {int(lim)}"
    return [env.from_verdict(v, "model", en, tr, measured=M(n, "storeys", prov), required=R("<=", lim, "storeys"),
                             anchor=anchor, dimensions=dl, source="building_model" if bm else "drawing_model",
                             extra={"habitable_basements": c.get("habitable_basements", 0)})]


# ----------------------------------------------------------------------------- parcel_dimensions
@register("parcel_dimensions")
def parcel_dimensions(env: Env) -> list[dict]:
    """One rule = one part (width|depth) of one storey band / zone; see check.extra in the catalogue."""
    part = env.params.get("part") or "width"
    pi, rev = _parcel_or_review(env, "parcel", "parcel width/depth (Madde 6)")
    if rev:
        return rev
    ctx = env.ctx
    fi = ctx.get("front_edge_index")
    pts = _open_poly(pi["polygon"])
    n, nsrc = _plan_storeys_first(env)
    base = env.limit("limit")
    if base is None:
        return [env.na("Rule has no limit value", "Kural sınır değeri içermiyor")]
    order = (ctx.get("building_order") or "detached").lower()
    reqs = setback_requirements(env, n)
    if part == "width":
        if env.params.get("formula") is None:        # industrial: fixed value
            req, note = base, "fixed minimum"
        elif order == "adjacent":
            req, note = base, "adjacent order"
        elif order == "block":
            req, note = reqs["side"][0] + base, f"block head: side setback {reqs['side'][0]:.2f} + {base:.2f} m"
        else:
            req, note = 2 * reqs["side"][0] + base, f"detached: side setbacks 2 x {reqs['side'][0]:.2f} + {base:.2f} m"
    else:
        front = reqs["front"][0]
        if env.params.get("formula") is None or front == 0:
            req, note = base, "no front garden" if front == 0 else "fixed minimum"
        else:
            req, note = front + base, f"front garden {front:.2f} + {base:.2f} m"
    ex_text = ("Madde 6(5): parcels formed by an earlier plan implementation are exempt from minimum frontage/depth/area - "
               "this rule is meant for new subdivisions (ifraz).")
    if fi is None:
        mr = min_rect(pts)
        return [env.review("parcel", "missing_context",
                           "Set front_edge_index (the parcel edge facing the road). For information the parcel's min-area rectangle is "
                           f"{fmt(mr['short'] if mr else None, 'm')} x {fmt(mr['long'] if mr else None, 'm')}.",
                           f"Parcel {part} cannot be assigned without the road edge (need {fmt(req, 'm')})",
                           f"Yol cephesi belirtilmediği için parsel {part} ölçülemedi (gereken {fmt(req, 'm')})",
                           source="parcel_context", view_id=pi["view_id"])]
    edges = classify_edges(pi["polygon"], fi, None)
    fe = edges[int(fi) % len(edges)]
    p, q = fe["p"], fe["q"]
    frontage = math.hypot(q[0] - p[0], q[1] - p[1])
    ux, uy = (q[0] - p[0]) / (frontage or 1), (q[1] - p[1]) / (frontage or 1)
    nx, ny = -uy, ux
    proj = [((pt[0] - p[0]) * nx + (pt[1] - p[1]) * ny) for pt in pts]
    if sum(proj) < 0:
        nx, ny, proj = -nx, -ny, [-x for x in proj]
    depth = max(proj)
    mid = ((p[0] + q[0]) / 2, (p[1] + q[1]) / 2)
    z = 0.0
    if part == "width":
        val, label_en, label_tr = frontage, "frontage (width)", "cephe genişliği"
        dl = [dim([p[0], p[1], z], [q[0], q[1], z], fmt(frontage, "m"), "linear")]
    else:
        val, label_en, label_tr = depth, "depth", "derinlik"
        dl = [dim([mid[0], mid[1], z], [mid[0] + nx * depth, mid[1] + ny * depth, z], fmt(depth, "m"), "linear")]
    prov = "inferred" if (n is None and part == "width" and env.params.get("formula")) else "geometry"
    v = judge(val, ">=", req, tol=env.tol(0.01), prov=prov, semi=env.semi, label=label_en)
    if v.status == "violation":
        v = Verdict("review", "exception_may_apply", ex_text, False)
    return [env.from_verdict(
        v, "parcel", f"Parcel {label_en} is {fmt(val, 'm')}; minimum {fmt(req, 'm')} ({note})",
        f"Parsel {label_tr} {fmt(val, 'm')}; en az {fmt(req, 'm')}", measured=M(val, "m", prov),
        required=R(">=", req, "m"), dimensions=dl, anchor=[mid[0], mid[1], z], source="parcel_context",
        view_id=pi["view_id"], extra={"storeys": n, "storeys_source": nsrc, "part": part})]
