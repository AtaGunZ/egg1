"""Hand-rolled glTF 2.0 binary writer (one node per IFC product, node extras, Y-up conversion)."""
from __future__ import annotations

import json
import struct

import numpy as np

SPACE_MAX_ALPHA = 0.25
DEFAULT_COLOR = (0.78, 0.78, 0.78, 1.0)
SPACE_COLOR = (0.35, 0.65, 0.95, SPACE_MAX_ALPHA)


def _pad4(b: bytes, pad=b"\x00") -> bytes:
    r = (-len(b)) % 4
    return b + pad * r


def to_yup(a: np.ndarray) -> np.ndarray:
    """(x,y,z)_ifc -> (x, z, -y)_gltf. Proper rotation (det = +1), triangle winding is preserved."""
    out = np.empty_like(a)
    out[:, 0] = a[:, 0]
    out[:, 1] = a[:, 2]
    out[:, 2] = -a[:, 1]
    return out


class GlbBuilder:
    def __init__(self):
        self.bin = bytearray()
        self.buffer_views = []
        self.accessors = []
        self.meshes = []
        self.nodes = []
        self.materials = []
        self._mat_index = {}
        self.root_children = []
        self.triangles = 0

    # -- materials ---------------------------------------------------------------------------------
    def material(self, rgba, name=None):
        key = tuple(round(float(c), 3) for c in rgba)
        idx = self._mat_index.get(key)
        if idx is not None:
            return idx
        r, g, b, a = key
        mat = {
            "name": name or f"mat_{len(self.materials)}",
            "pbrMetallicRoughness": {"baseColorFactor": [r, g, b, a], "metallicFactor": 0.0, "roughnessFactor": 0.85},
            "doubleSided": True,
            "alphaMode": "BLEND" if a < 0.999 else "OPAQUE",
        }
        self.materials.append(mat)
        self._mat_index[key] = len(self.materials) - 1
        return self._mat_index[key]

    # -- geometry ---------------------------------------------------------------------------------------
    def _add_accessor(self, data: np.ndarray, target, minmax=False):
        raw = np.ascontiguousarray(data, dtype=np.float32).tobytes()
        offset = len(self.bin)
        self.bin += raw
        self.bin += b"\x00" * ((-len(raw)) % 4)
        self.buffer_views.append({"buffer": 0, "byteOffset": offset, "byteLength": len(raw), "target": target})
        acc = {"bufferView": len(self.buffer_views) - 1, "componentType": 5126, "count": int(len(data)), "type": "VEC3"}
        if minmax:
            acc["min"] = [float(x) for x in data.min(axis=0)]
            acc["max"] = [float(x) for x in data.max(axis=0)]
        self.accessors.append(acc)
        return len(self.accessors) - 1

    def add_mesh(self, tri_ifc: np.ndarray, mat_ids: np.ndarray, materials: list, is_space: bool, name: str):
        """tri_ifc: (m,3,3) world Z-up. Returns mesh index (one primitive per material)."""
        n = np.cross(tri_ifc[:, 1] - tri_ifc[:, 0], tri_ifc[:, 2] - tri_ifc[:, 0])
        ln = np.linalg.norm(n, axis=1)
        keep = ln > 1e-14
        if not keep.any():
            return None
        tri_ifc, n, ln, mat_ids = tri_ifc[keep], n[keep], ln[keep], mat_ids[keep]
        n = n / ln[:, None]
        prims = []
        for mid in np.unique(mat_ids):
            sel = mat_ids == mid
            t = tri_ifc[sel]
            nn = n[sel]
            pos = to_yup(t.reshape(-1, 3))
            nrm = to_yup(np.repeat(nn, 3, axis=0))
            if 0 <= mid < len(materials):
                r, g, b, a = materials[mid][:4]
                rgba = (r, g, b, a)
                if is_space:
                    rgba = (r, g, b, min(a, SPACE_MAX_ALPHA))
            else:
                rgba = SPACE_COLOR if is_space else DEFAULT_COLOR
            pa = self._add_accessor(pos, 34962, minmax=True)
            na = self._add_accessor(nrm, 34962)
            prims.append({"attributes": {"POSITION": pa, "NORMAL": na}, "material": self.material(rgba), "mode": 4})
            self.triangles += int(sel.sum())
        self.meshes.append({"name": name, "primitives": prims})
        return len(self.meshes) - 1

    def add_node(self, name, extras, mesh=None, children=None):
        node = {"name": name, "extras": extras}
        if mesh is not None:
            node["mesh"] = mesh
        if children is not None:
            node["children"] = children
        self.nodes.append(node)
        return len(self.nodes) - 1

    def finish(self, out_path: str, scene_name="BIMCheck"):
        doc = {
            "asset": {"version": "2.0", "generator": "bimcheck.ingest.ifc", "extras": {"source_axes": "IFC Z-up -> glTF Y-up (x,z,-y)", "unit": "metre"}},
            "scene": 0,
            "scenes": [{"name": scene_name, "nodes": self.root_children}],
            "nodes": self.nodes,
            "meshes": self.meshes,
            "materials": self.materials,
            "accessors": self.accessors,
            "bufferViews": self.buffer_views,
            "buffers": [{"byteLength": len(self.bin)}],
        }
        if not self.meshes:
            for k in ("meshes", "materials", "accessors", "bufferViews", "buffers"):
                doc.pop(k, None)
        js = _pad4(json.dumps(doc, separators=(",", ":")).encode("utf-8"), b" ")
        binc = _pad4(bytes(self.bin))
        parts = [struct.pack("<II", len(js), 0x4E4F534A), js]
        if self.meshes:
            parts += [struct.pack("<II", len(binc), 0x004E4942), binc]
        body = b"".join(parts)
        header = struct.pack("<III", 0x46546C67, 2, 12 + len(body))
        with open(out_path, "wb") as f:
            f.write(header + body)
