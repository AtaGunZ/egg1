"""Flattened scene: model-space entities + expanded INSERT contents, each with a bbox and (optionally) a view id."""
from __future__ import annotations

import math
from dataclasses import dataclass, field

import numpy as np

from . import geom
from .reader import RawDrawing


@dataclass
class Scene:
    raw: RawDrawing
    ents: list[dict]                 # linework / hatch / solid / dim / point entities (incl. expanded block content)
    texts: list[dict]                # TEXT/MTEXT (incl. block attribs and block text)
    inserts: list[dict]              # model-space INSERT entities (not expanded)
    layer_names: list[str]
    extents: tuple[float, float, float, float]
    bboxes: np.ndarray = field(default=None)   # (n, 4) of ents


def build_scene(raw: RawDrawing, expand_blocks: bool = True) -> Scene:
    ents: list[dict] = []
    texts: list[dict] = []
    inserts: list[dict] = []
    skip_blocks = {n for n in raw.blocks if n.startswith("*D") or n.startswith("*d")}
    for e in raw.entities:
        t = e["t"]
        if t == "TEXT":
            texts.append(e)
        elif t == "INSERT":
            inserts.append(e)
            for a in e.get("attribs", []):
                if a.get("text"):
                    texts.append({"t": "TEXT", "layer": e["layer"], "text": a["text"], "pos": a["pos"], "h": 0.0, "rot": 0.0, "mtext": False,
                                  "tag": a.get("tag"), "from_attrib": True})
            if expand_blocks and e["name"] not in skip_blocks:
                for x in geom.expand_insert(e, raw.blocks, raw.block_base):
                    x["ins_name"] = e["name"]
                    if x["t"] == "TEXT":
                        texts.append(x)
                    else:
                        ents.append(x)
        elif t == "OTHER":
            ents.append(e)
        else:
            ents.append(e)
    bbs = []
    keep = []
    for e in ents:
        b = geom.entity_bbox(e)
        if b is None or not all(math.isfinite(v) for v in b):
            if e["t"] != "OTHER":
                continue
            b = (math.nan,) * 4
        e["bb"] = b
        bbs.append(b)
        keep.append(e)
    arr = np.array(bbs, dtype=float) if bbs else np.zeros((0, 4))
    mask = np.array([not e.get('blk') for e in keep], dtype=bool) if len(keep) else np.zeros(0, bool)
    finite = arr[mask & np.isfinite(arr).all(axis=1)] if len(arr) else arr
    if len(finite):
        # robust extents: ignore stray far-away entities (0.2% tails)
        cx = (finite[:, 0] + finite[:, 2]) / 2
        cy = (finite[:, 1] + finite[:, 3]) / 2
        lo_x, hi_x = np.percentile(cx, [0.5, 99.5])
        lo_y, hi_y = np.percentile(cy, [0.5, 99.5])
        extents = (float(lo_x), float(lo_y), float(hi_x), float(hi_y))
    else:
        extents = (0.0, 0.0, 1.0, 1.0)
    for t_ in texts:
        pass
    return Scene(raw=raw, ents=keep, texts=texts, inserts=inserts, layer_names=[l["name"] for l in raw.layers], extents=extents, bboxes=arr[[i for i in range(len(arr))]] if len(arr) else arr)
