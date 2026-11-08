import os
import numpy as np
import pytest
import trimesh
from bimcheck.ingest.ifc import extract_building_model, export_geometry_glb

S = os.path.join(os.path.dirname(__file__), "..", "..", "samples")
FZK = os.path.join(S, "AC20-FZK-Haus.ifc")
DUP = os.path.join(S, "Duplex_A_20110907.ifc")


@pytest.fixture(scope="module")
def fzk():
    return extract_building_model(FZK)


@pytest.fixture(scope="module")
def dup():
    return extract_building_model(DUP)


def of(m, kind):
    return [e for e in m["elements"] if e["kind"] == kind]


def test_fzk(fzk):
    assert fzk["source"]["ifc_schema"] == "IFC4" and fzk["source"]["length_unit_scale_to_m"] == 1.0
    assert [s["name"] for s in fzk["storeys"]] == ["Erdgeschoss", "Dachgeschoss"]
    assert fzk["storeys"][1]["elevation"] == 2.7
    sp = {e["long_name"]: e for e in of(fzk, "space")}
    assert len(sp) == 7
    assert sp["Schlafzimmer"]["measures"]["usage"] == "bedroom"
    assert sp["Küche"]["measures"]["usage"] == "kitchen"
    w = sp["Wohnen"]["measures"]
    assert abs(w["geometry_floor_area"] - 25.99) < 0.1 and w["height"] == 2.5 and w["has_exterior_window"] is True
    for d in of(fzk, "door"):
        assert 0.75 <= d["measures"]["width"] <= 2.1 and 1.9 <= d["measures"]["height"] <= 2.4
    assert sum(1 for d in of(fzk, "door") if d["measures"]["is_entrance"]) == 1
    st = of(fzk, "stair")[0]["measures"]
    assert 0.15 < st["riser_height"] < 0.2 and st["step_count"] in (15, 16)


def test_duplex(dup):
    assert dup["source"]["ifc_schema"] == "IFC2X3"
    assert [s["name"] for s in dup["storeys"]] == ["T/FDN", "Level 1", "Level 2", "Roof"]
    assert dup["storeys"][0]["is_underground"]
    assert len(of(dup, "space")) == 21
    for s in of(dup, "stair"):
        m = s["measures"]
        assert abs(m["riser_height"] - 0.19375) < 1e-3 and m["step_count"] == 16 and m["tread_depth"] == 0.25
    for e in of(dup, "door") + of(dup, "window"):
        assert 0.5 < e["measures"]["width"] < 5.0
    living = [e for e in of(dup, "space") if e["long_name"] == "Living Room"][0]["measures"]
    assert 25 < living["net_floor_area"] < 32 and living["height"] == 2.6 and living["usage"] == "living_room"


@pytest.mark.parametrize("path", [FZK, DUP])
def test_glb(path, tmp_path):
    out = tmp_path / "m.glb"
    r = export_geometry_glb(path, out)
    m = extract_building_model(path)
    sc = trimesh.load(str(out))
    assert r["nodes"] > 50 and r["triangles"] > 1000
    els = [e for e in m["elements"] if e["ifc_class"] != "IfcSite"]
    mn = np.min([e["bbox"]["min"] for e in els], 0)
    mx = np.max([e["bbox"]["max"] for e in els], 0)
    # Y-up: gltf (x, z, -y)
    assert np.allclose(r["bounds"]["min"], mn, atol=0.01) and np.allclose(r["bounds"]["max"], mx, atol=0.01)
    b = sc.bounds
    assert b[0][1] <= mn[2] + 0.01 and b[1][1] >= mx[2] - 0.01
    assert any(n == els[0]["guid"] for n in sc.graph.nodes)
