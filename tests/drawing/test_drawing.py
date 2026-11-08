import os
import pytest
from bimcheck.ingest.drawing import extract_drawing_model

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
S = os.path.join(ROOT, "samples")


@pytest.mark.slow
def test_mimari():
    m = extract_drawing_model(os.path.join(S, "mimari-onayli.dwg"))
    assert m["source"]["units"] == "cm" and m["source"]["unit_scale_to_m"] == 0.01
    assert abs(m["parcel"]["area"] - 836.35) < 5
    assert 250 < m["footprint"]["area"] < 320
    assert any(v["kind"] == "floor_plan" and v["level_hint"] == 0 for v in m["views"])
    assert len(m["rooms"]) > 20


@pytest.mark.slow
def test_vaziyet():
    m = extract_drawing_model(os.path.join(S, "vaziyet-3d.dwg"))
    assert m["parcel"] is None and m["warnings"]
