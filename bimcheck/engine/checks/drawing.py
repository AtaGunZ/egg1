"""Drawing-model-only checks."""
from __future__ import annotations

from ..finding import Env, M, R
from ..util import dim, fmt, num, poly_centroid
from . import register


@register("drawing_area_mismatch")
def drawing_area_mismatch(env: Env) -> list[dict]:
    """Labelled room area (text in the DWG) vs area computed from the room polygon."""
    dm = env.dm
    if dm is None or not dm.rooms:
        return [env.na("Requires a drawing model with rooms", "Oda içeren bir çizim modeli gerekir")]
    rel = float(env.params.get("rel_tolerance", 0.05))
    absol = float(env.params.get("abs_tolerance", 0.30))
    out = []
    n_unlabelled = 0
    for r in dm.rooms:
        la, ca = num(r.get("labelled_area")), num(r.get("area"))
        if la is None or ca is None:
            n_unlabelled += 1
            continue
        diff = abs(la - ca)
        nm = r.get("name") or r.get("id")
        poly = r.get("polygon") or []
        lp = r.get("label_point") or (list(poly_centroid(poly)) if len(poly) >= 3 else None)
        z = 0.0
        bad = diff > max(absol, rel * la)
        dl = []
        if lp:
            dl = [dim([lp[0], lp[1], z], [lp[0] + 1.0, lp[1], z], f"label {fmt(la, 'm²')} / computed {fmt(ca, 'm²')}", "area")]
        st = "review" if bad else "pass"
        out.append(env.finding(
            st, f"dm:{r.get('id')}",
            f"Room '{nm}': labelled area {fmt(la, 'm²')} vs polygon area {fmt(ca, 'm²')} (difference {fmt(diff, 'm²')})",
            f"Oda '{nm}': etiket alanı {fmt(la, 'm²')} / poligon alanı {fmt(ca, 'm²')} (fark {fmt(diff, 'm²')})",
            reason="low_confidence" if bad else None,
            hint="The area written on the drawing does not match the room outline - either the label is stale or the room "
                 "polygon was detected wrongly." if bad else None,
            anchor=[lp[0], lp[1], z] if lp else None, measured=M(ca, "m²", "geometry"),
            required=R("==", la, "m²"), dimensions=dl, source="drawing_model", view_id=r.get("view_id")))
    if not out:
        return [env.na(f"No rooms carry a labelled area ({n_unlabelled} room(s) checked)", "Alan etiketi olan oda yok")]
    return out
