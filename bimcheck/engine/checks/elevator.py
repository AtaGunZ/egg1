"""Madde 34 - elevator obligation."""
from __future__ import annotations

from ..finding import Env, M, R
from ..util import dim, num
from . import register
from .common import model_bounds, model_center


@register("elevator_required")
def elevator_required(env: Env) -> list[dict]:
    bm = env.bm
    ctx = env.ctx
    if env.params.get("part") == "count":
        return _lift_count(env)
    plan_n = num(ctx.get("max_storeys"))
    plan_n = int(plan_n) if plan_n is not None else None
    if bm is None and plan_n is None:
        return [env.review("model", "missing_context",
                           "Provide an IFC model or the plan's storey count (max_storeys) to decide whether a lift is required.",
                           "Storey count unknown - lift obligation (Madde 34) cannot be evaluated",
                           "Kat adedi bilinmiyor - asansör zorunluluğu (Madde 34) değerlendirilemedi")]
    counts = bm.storey_counts() if bm else None
    n_model = counts["total"] if counts else None
    unc = counts["uncertain_basements"] if counts else 0
    n_eff = max(n_model or 0, plan_n or 0)
    ctx_lift = ctx.get("has_elevator")
    ev, ev_guids = bm.lift_evidence() if bm else ("none", [])
    single = ctx.get("is_single_dwelling")

    anchor = None
    dlist: list[dict] = []
    if bm:
        b = model_bounds(bm)
        c = model_center(bm)
        g = bm.ground_storey
        z0 = (num(g.get("elevation")) if g else None) or (b[0][2] if b else 0.0)
        if c:
            top = bm.storey_counts()["above_storeys"]
            z1 = (num(top[-1].get("elevation")) if top else None)
            if z1 is None:
                z1 = z0
            anchor = [c[0], c[1], z0]
            dlist = [dim([b[0][0], b[0][1], z0], [b[0][0], b[0][1], z1 if z1 > z0 else z0 + 0.01],
                         f"{n_eff} storeys", "linear")]
    measured = M(n_eff, "storeys", "geometry" if n_model else "inferred")
    base = dict(elements=[], context_elements=ev_guids[:6], anchor=anchor, dimensions=dlist,
                source="building_model" if bm else "parcel_context", measured=measured,
                extra={"storeys_in_model": n_model, "storeys_in_plan": plan_n, "lift_evidence": ev,
                       "uncertain_basements": unc})

    if n_eff <= 2 and not unc:
        return [env.na(f"Building has {n_eff} storey(s): a lift is not mandatory (Madde 34)",
                       f"Bina {n_eff} katlı: asansör zorunlu değil (Madde 34)", **base)]
    if single is True:
        return [env.na("Single-unit dwelling: exempt from the lift obligation (Madde 34(1))",
                       "Tek bağımsız bölümlü konut: asansör zorunluluğundan muaf (Madde 34(1))", **base)]
    if n_eff <= 2 and unc:
        return [env.review("model", "missing_measure",
                           "An underground storey has spaces of unclassified use; if it is habitable or holds a dwelling "
                           "it counts towards the 4-storey threshold - classify its spaces.",
                           f"Lift obligation depends on whether the basement counts ({n_eff} storeys + {unc} unclear basement)",
                           f"Asansör zorunluluğu bodrum katın sayılıp sayılmadığına bağlı ({n_eff} kat + {unc} belirsiz bodrum)",
                           **base)]

    required_lift = n_eff >= 4
    req = R("exists", None, "")
    req["value"] = "lift" if required_lift else "lift space"
    present = ctx_lift is True or (ctx_lift is None and ev == "element")

    def done(status, en, tr, reason=None, hint=None):
        return [env.finding(status, "model", en, tr, reason=reason, hint=hint, required=req,
                            **{k: v for k, v in base.items() if k not in ()})]

    if required_lift:
        what_en = f"{n_eff} storeys (>=4): a lift is mandatory (Madde 34(1))"
        what_tr = f"{n_eff} kat (>=4): asansör zorunludur (Madde 34(1))"
        if present:
            return done("pass", what_en + " - lift present", what_tr + " - asansör mevcut")
        if ctx_lift is False:
            if plan_n and plan_n > (n_model or 0) and (n_model or 0) < 4:
                return done("review", what_en + " - none planned; but the model has fewer storeys than the plan",
                            what_tr + " - yok; ancak model plandan az katlı", "legal_judgement",
                            "Plan allows >=4 storeys but the model has fewer (eksik katlı, Madde 25): a lift is required "
                            "if the missing storeys are added - confirm the intended design.")
            return done("violation", what_en + " - none provided", what_tr + " - asansör öngörülmemiş")
        if ev == "space":
            return done("review", what_en + " - only a lift-shaft space was found", what_tr + " - yalnızca asansör kovası mekânı bulundu",
                        "low_confidence", "A lift shaft space exists but no lift equipment is modelled; confirm a lift is installed.")
        return done("review", what_en + " - no lift found in the model", what_tr + " - modelde asansör bulunamadı",
                    "missing_measure", "No IfcTransportElement or lift-named element found. IFC exports often omit lifts: "
                                       "confirm on the drawings or set has_elevator in the project context.")
    # n_eff == 3
    what_en = "3 storeys: space for a lift must be left (Madde 34(1))"
    what_tr = "3 kat: asansör yeri bırakılmalıdır (Madde 34(1))"
    if present:
        return done("pass", what_en + " - lift present", what_tr + " - asansör mevcut")
    if ev == "space":
        return done("pass", what_en + " - lift shaft space found", what_tr + " - asansör kovası mekânı bulundu")
    return done("review", what_en + " - cannot be verified from the model", what_tr + " - modelden doğrulanamadı",
                "missing_measure", "Check on the plans that a shaft area for a future lift is reserved "
                                   "(or set has_elevator in the project context).")


def _lift_count(env: Env) -> list[dict]:
    """Madde 34(4): at least 2 lifts for >=10 storeys / large public buildings / >20 units above the entrance floor."""
    bm = env.bm
    if bm is None:
        return [env.na("Requires a building model", "Yapı modeli gerekir")]
    n = bm.storey_counts()["total"]
    area = 0.0
    for s in bm.storey_counts()["above_storeys"]:
        a, _ = bm.storey_floor_area(s)
        area = max(area, a or 0.0)
    public = env.use in ("commercial", "other") or bool(env.ctx.get("is_public_building"))
    trig = []
    if n >= 10:
        trig.append(">= 10 storeys")
    if public and area > 800 and n > 3:
        trig.append("public building, floor area > 800 m2 and > 3 storeys")
    if not trig:
        return [env.na("No trigger for two lifts (needs >= 10 storeys, or a public building > 800 m2 and > 3 storeys; "
                       "the 'more than 20 units' trigger cannot be checked)", "İki asansör zorunluluğunu doğuran koşul yok")]
    if env.ctx.get("has_elevator") is False:
        have, ev, guids = 0, "context", []
    else:
        ev, guids = bm.lift_evidence()
        have = len(guids) if ev == "element" else None
    base = dict(measured=M(have, "lifts", "geometry" if have is not None else None), required=R(">=", 2, "lifts"),
                context_elements=guids[:6])
    if have is None:
        return [env.review("model", "missing_measure", "No lift elements found in the model; count the lifts on the plans.",
                           f"At least 2 lifts required ({'; '.join(trig)}); none found in the model",
                           "En az 2 asansör gerekli; modelde asansör bulunamadı", **base)]
    st = "pass" if have >= 2 else "violation"
    if st == "violation" and ev == "element":
        st = "review"  # IFC lift elements may be merged/omitted
    return [env.finding(st, "model", f"{have} lift(s) in the model; at least 2 required ({'; '.join(trig)})",
                        f"Modelde {have} asansör var; en az 2 gerekli",
                        reason="low_confidence" if st == "review" else None,
                        hint="Lifts are counted from model elements, which may be incomplete - confirm on the plans."
                        if st == "review" else None, **base)]
