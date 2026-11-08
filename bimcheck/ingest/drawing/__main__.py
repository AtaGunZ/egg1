"""Debug CLI: python -m bimcheck.ingest.drawing <file> [--json out.json] [--preview out.png]"""
from __future__ import annotations

import argparse
import json
import sys


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="python -m bimcheck.ingest.drawing")
    ap.add_argument("file")
    ap.add_argument("--json")
    ap.add_argument("--preview")
    a = ap.parse_args(argv)
    from . import extract_drawing_model

    dbg: dict = {}
    m = extract_drawing_model(a.file, _debug=dbg)
    if a.json:
        with open(a.json, "w", encoding="utf-8") as f:
            json.dump(m, f, ensure_ascii=False, indent=1)
    if a.preview:
        render_preview(m, dbg, a.preview)
    s = m["source"]
    print(f"{s['file']}: units={s['units']} ({s['unit_source']}) views={len(m['views'])} rooms={len(m['rooms'])} "
          f"parcel={m['parcel'] and m['parcel']['area']} footprint={m['footprint'] and m['footprint']['area']}")
    for w in m["warnings"]:
        print("  warning:", w)
    return 0


def render_preview(m: dict, dbg: dict, out: str) -> None:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib.collections import LineCollection

    from . import geom

    sc, vf, roles = dbg["scene"], dbg["vf"], dbg["roles"]
    panels = []
    if m["parcel"]:
        panels.append(m["parcel"]["view_id"])
    for r in m["rooms"]:
        if r["polygon"] and r["view_id"] not in panels:
            panels.append(r["view_id"])
    if m["footprint"] and m["footprint"]["view_id"] not in panels:
        panels.append(m["footprint"]["view_id"])
    panels = panels[:4]
    fig, axes = plt.subplots(1, 1 + len(panels), figsize=(7 * (1 + len(panels)), 7), squeeze=False)
    axes = axes[0]
    ax = axes[0]
    for v in dbg["views"]:
        b = v["bbox_raw"]
        ax.add_patch(plt.Rectangle((b[0], b[1]), b[2] - b[0], b[3] - b[1], fill=False, ec="r" if v["kind"] == "floor_plan" else "b", lw=0.6))
        ax.text(b[0], b[3], f"{v['id']} {v['kind']}\n{(v['name'] or '')[:22]}", fontsize=5, va="top")
    ax.set_xlim(min(v["bbox_raw"][0] for v in dbg["views"]), max(v["bbox_raw"][2] for v in dbg["views"]))
    ax.set_ylim(min(v["bbox_raw"][1] for v in dbg["views"]), max(v["bbox_raw"][3] for v in dbg["views"]))
    ax.set_aspect("equal")
    ax.set_title("views (raw drawing units)")
    for ax, vid in zip(axes[1:], panels):
        f = vf[vid]
        segs = []
        for e in sc.ents:
            if e.get("view") == vid and e["t"] in ("LINE", "POLY") and roles.get(e["layer"]) in ("wall", "column", "parcel", "window", "door") and not e.get("blk"):
                for pts, _ in geom.entity_lines(e):
                    segs.append([(x * f, y * f) for x, y in pts])
        ax.add_collection(LineCollection(segs, colors="#888", linewidths=0.4))
        for r in m["rooms"]:
            if r["view_id"] == vid and r["polygon"]:
                xs, ys = zip(*r["polygon"])
                ax.fill(xs, ys, alpha=0.35)
                ax.text(*r["label_point"], f"{r['name'][:14]}\n{r['area']}/{r['labelled_area']}", fontsize=4)
        for key, col in (("parcel", "r"), ("footprint", "g")):
            o = m[key]
            if o and o["view_id"] == vid:
                xs, ys = zip(*(o["polygon"] + [o["polygon"][0]]))
                ax.plot(xs, ys, col, lw=1.5)
        sf = m["extra"].get("site_footprint")
        if sf and sf["view_id"] == vid:
            xs, ys = zip(*(sf["polygon"] + [sf["polygon"][0]]))
            ax.plot(xs, ys, "g", lw=1.5)
        v = next(v for v in m["views"] if v["id"] == vid)
        ax.set_xlim(v["bbox"][0], v["bbox"][2])
        ax.set_ylim(v["bbox"][1], v["bbox"][3])
        ax.set_aspect("equal")
        ax.set_title(f"{vid} {v['name']} (metres)", fontsize=8)
    fig.savefig(out, dpi=80, bbox_inches="tight")


if __name__ == "__main__":
    sys.exit(main())
