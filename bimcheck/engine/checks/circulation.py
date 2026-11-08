"""Madde 30(1) - building entrance corridor width."""
from __future__ import annotations

from .. import dims
from ..finding import Env, M, R, describe
from ..judge import Verdict, judge
from ..util import min_rect, num
from ..view import USAGE_EN, USAGE_TR, ModelView
from . import register
from .common import need_building_model
from .openings import classify_door

CORRIDOR_USAGES = {"corridor", "hall", "stair", "other", None}


@register("entrance_corridor_width")
def entrance_corridor_width(env: Env) -> list[dict]:
    na = need_building_model(env, "doors and spaces")
    if na:
        return na
    bm = env.bm
    if env.ctx.get("is_single_dwelling") is True:
        return [env.na("Single dwelling: the building-entrance corridor rule (Madde 30(1)) is not applied",
                       "Tek konut: bina giriş koridoru kuralı (Madde 30(1)) uygulanmadı")]
    public = bool(env.ctx.get("is_public_building")) or env.use in ("commercial", "other")
    lim = env.limit("limit") if env.overridden("limit") else (2.20 if public else 1.50)
    basis = "public building" if public else "other buildings"
    tol = env.tol(0.005)
    ground = bm.ground_storey
    entrances = []
    for d in bm.of_kind("door"):
        cls, _ = classify_door(env, d)
        if cls in ("building_entrance", "entrance_candidate"):
            if ground is None or d.get("storey_id") in (None, ground["id"]):
                entrances.append((d, cls))
    spaces: dict[str, dict] = {}
    confident = False
    for d, cls in entrances:
        for g in (d.get("measures") or {}).get("space_guids") or []:
            s = bm.by_guid.get(g)
            if s and (s.get("measures") or {}).get("usage") in CORRIDOR_USAGES:
                spaces[g] = s
                confident = confident or cls == "building_entrance"
    fallback = False
    if not spaces and ground is not None:
        for s in bm.storey_spaces(ground["id"]):
            if (s.get("measures") or {}).get("usage") in ("corridor", "hall"):
                spaces[s["guid"]] = s
                fallback = True
    if not spaces:
        return [env.review("model", "missing_measure",
                           "No entrance door with an adjoining corridor/hall could be identified on the ground storey; "
                           "measure the entrance corridor on the plan.",
                           "Entrance corridor could not be identified in the model",
                           "Giriş koridoru modelde belirlenemedi")]
    door_w = max([num((d.get("measures") or {}).get("width")) or 0.0 for d, _ in entrances] or [0.0])
    lim_eff = max(lim, door_w) if not env.overridden("limit") else lim
    out = []
    for g, s in spaces.items():
        ms = s.get("measures") or {}
        w, p = num(ms.get("min_width")), (s.get("provenance") or {}).get("min_width")
        if w is None and ms.get("footprint"):
            mr = min_rect(ms["footprint"])
            if mr:
                w, p = mr["short"], "geometry"
        usage = ms.get("usage") or "other"
        nm = ModelView.name(s)
        subj_en, subj_tr = f"{USAGE_EN.get(usage, 'Space')} '{nm}'", f"{USAGE_TR.get(usage, 'Mekân')} '{nm}'"
        v = judge(w, ">=", lim_eff, tol=tol, prov=p, min_prov=env.min_provenance, semi=env.semi,
                  exceptions=env.exceptions, legal=env.legal, label="corridor width")
        if v.status == "violation" and (fallback or not confident):
            v = Verdict("review", "low_confidence",
                        "This space was picked as the entrance corridor by heuristics (no entrance door marked); "
                        "confirm it is the corridor between the entrance door and the main stair/lift.", False)
        en, tr = describe(subj_en, subj_tr, "entrance corridor width", "giriş koridoru genişliği", w, "m", ">=", lim_eff)
        en += f" ({basis}{', not smaller than the outer door' if lim_eff > lim else ''})"
        out.append(env.from_verdict(v, g, en, tr, measured=M(w, "m", p), required=R(">=", lim_eff, "m"),
                                    elements=[g], context_elements=[d["guid"] for d, _ in entrances][:4],
                                    storey_id=s.get("storey_id"), anchor=bm.anchor(s),
                                    dimensions=dims.space_dims(bm, s, "min_width", w)))
    return out
