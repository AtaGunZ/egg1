"""Madde 28(1) - floor-to-floor storey heights."""
from __future__ import annotations

from ..finding import Env, M, R, describe
from ..judge import judge
from ..util import dim, fmt, num
from ..view import ModelView
from . import register
from .common import need_building_model, storey_anchor

MAX_MEZZANINE = 6.50  # amended value (5.50 -> 6.50) for ground storeys with a mezzanine
HOUSING = {"living_room", "bedroom"}


def storey_limit(env: Env, bm: ModelView, st: dict) -> tuple[float | None, str, list[str], str | None]:
    """(limit, basis, exception_texts, reason_if_unknowable)."""
    use = env.use
    zl = env.rule_extra.get("zone_type")
    zone = (zl[0] if isinstance(zl, list) and zl else (zl or env.ctx.get("zone_type") or "")).lower()
    sk = bm.storey_kind(st)
    ground = sk == "ground" or (len(bm.above_ground) == 1)
    usages = {bm.measure(s, "usage") for s in bm.storey_spaces(st["id"])}
    dwelling = bool(usages & HOUSING)
    commerce = "commercial" in usages
    n = bm.storey_counts()["total"]
    ex: list[str] = []
    if zone == "ticaret" or (not zone and use == "commercial"):
        lim = 4.50 if ground else 4.00
        basis = "commercial zone (Madde 28(1)a)"
        if ground:
            ex.append(f"Ground storey with mezzanine (asma kat): up to {MAX_MEZZANINE:.2f} m (Madde 28(1)a)")
    elif zone == "karma" or (not zone and use == "mixed" and zone != "konut"):
        if ground:
            lim, basis = 4.50, "mixed zone, ground storey (Madde 28(1)b)"
            ex.append(f"Ground storey with mezzanine (asma kat): up to {MAX_MEZZANINE:.2f} m (Madde 28(1)b)")
        else:
            lim = 3.60 if dwelling or not usages else 4.00
            basis = "mixed zone, " + ("dwelling storey 3.60 m" if lim == 3.60 else "non-dwelling storey 4.00 m") + " (Madde 28(1)b)"
    elif use in ("residential", None) or zone == "konut" or use == "mixed":
        if ground and (commerce or use == "mixed"):
            lim, basis = 4.50, "residential zone, ground storey with shops (Madde 28(1)ç)"
            ex.append(f"Ground storey with mezzanine (asma kat): up to {MAX_MEZZANINE:.2f} m (Madde 28(1)ç)")
        else:
            lim, basis = 3.60, "residential zone (Madde 28(1)c)"
            if n <= 3:
                ex.append("Traditional stone-masonry buildings up to 3 storeys incl. ground: up to 4.50 m (Madde 28(1)d)")
            if ground:
                ex.append("Ground storey with shops allowed by the plan: up to 4.50 m (Madde 28(1)ç)")
    else:
        return None, "special building type", [], "legal_judgement"
    return lim, basis, ex, None


@register("storey_height_max")
def storey_height_max(env: Env) -> list[dict]:
    na = need_building_model(env, "storeys")
    if na:
        return na
    bm = env.bm
    storeys = [s for s in bm.storeys if not s.get("is_underground")]
    if not storeys:
        return [env.na("No above-ground storeys in the model", "Modelde zemin üstü kat yok")]
    tol = env.tol(0.005)
    out: list[dict] = []
    skipped: list[str] = []
    only_ground = bool(env.rule_extra.get("ground_floor_commerce"))
    zl = env.rule_extra.get("zone_type")
    konut_rule = isinstance(zl, list) and zl == ["konut"] and not only_ground
    for st in storeys:
        if only_ground and bm.storey_kind(st) != "ground" and len(bm.above_ground) > 1:
            continue
        if konut_rule and bm.storey_kind(st) == "ground" and any(
                bm.measure(s, "usage") == "commercial" for s in bm.storey_spaces(st["id"])):
            continue  # ground storey with shops is covered by the commerce variant of the rule
        h = bm.storey_height(st)
        name = st.get("name") or st["id"]
        if h is None:
            skipped.append(name)
            continue
        if not bm.storey_has_content(st["id"]):
            skipped.append(f"{name} (no content)")
            continue
        lim, basis, ex, why = storey_limit(env, bm, st)
        if env.overridden("limit"):
            lim, basis, ex, why = env.limit("limit"), "project override", [], None
        a = storey_anchor(bm, st)
        i = bm.storeys.index(st)
        nxt = bm.storeys[i + 1] if i + 1 < len(bm.storeys) else None
        z0 = num(st.get("elevation")) or 0.0
        dl = []
        if a:
            dl = [dim([a[0], a[1], z0], [a[0], a[1], z0 + h], f"floor-to-floor {fmt(h, 'm')}", "clearance")]
        slabs = [e["guid"] for e in bm.of_kind("slab") if e.get("storey_id") in (st["id"], nxt and nxt["id"])
                 and not bm.measure(e, "is_roof")][:8]
        subj_en, subj_tr = f"Storey '{name}'", f"Kat '{name}'"
        base = dict(elements=[], context_elements=slabs, storey_id=st["id"], anchor=a, dimensions=dl)
        if why:
            out.append(env.review(st["id"], why, "This building type is outside the standard storey-height table "
                                  "(Madde 28(7): decided by the architectural aesthetics committee).",
                                  f"{subj_en}: floor-to-floor height is {fmt(h, 'm')}; no standard limit for this building type",
                                  f"{subj_tr}: kat yüksekliği {fmt(h, 'm')}; bu yapı tipi için standart sınır yok",
                                  measured=M(h, "m", "geometry"), **base))
            continue
        v = judge(h, "<=", lim, tol=tol, prov="geometry", min_prov=None, semi=env.semi,
                  exceptions=ex + env.exceptions, legal=env.legal, label="floor-to-floor height")
        en, tr = describe(subj_en, subj_tr, "floor-to-floor height", "kat yüksekliği (döşeme üstü - döşeme üstü)", h, "m", "<=", lim)
        en += f" - {basis}"
        out.append(env.from_verdict(v, st["id"], en, tr, measured=M(h, "m", "geometry"), required=R("<=", lim, "m"), **base))
    if skipped:
        out.append(env.na("Not evaluated (no next floor level or empty storey): " + ", ".join(skipped),
                          "Değerlendirilmedi (üst kat kotu yok veya boş kat): " + ", ".join(skipped), key="skipped-storeys"))
    if not [f for f in out if f["status"] != "not_applicable"] and not out:
        return [env.na("No storey heights available", "Kat yüksekliği verisi yok")]
    return out
