import json
import time
from pathlib import Path

import pytest

from bimcheck.engine import run_check

FIX = Path(__file__).resolve().parents[1] / "fixtures"
RULES = Path(__file__).resolve().parents[2] / "rules" / "kayseri.rules.json"
REQUIRED = {"id", "rule_id", "status", "severity", "message_en", "message_tr", "measured", "required", "review_reason",
            "review_hint", "element_guids", "storey_id", "storey_name", "highlight", "anchor", "dimensions",
            "regulation_excerpt", "source", "view_id"}


@pytest.mark.skipif(not RULES.exists(), reason="catalogue not generated")
@pytest.mark.parametrize("name", ["duplex", "fzk"])
def test_real_fixture_smoke(name):
    p = FIX / f"{name}.building_model.json"
    if not p.exists():
        pytest.skip("fixture missing")
    bm = json.loads(p.read_text(encoding="utf-8"))
    t = time.time()
    r = run_check(bm, None, {})
    assert time.time() - t < 2
    assert not r["summary"]["errors"], r["summary"]["errors"]
    ids = [f["id"] for f in r["findings"]]
    assert len(ids) == len(set(ids))
    for f in r["findings"]:
        assert REQUIRED <= set(f), REQUIRED - set(f)
        assert f["status"] in ("violation", "review", "pass", "not_applicable")
        if f["status"] == "review":
            assert f["review_reason"] and f["review_hint"]
    assert r["summary"]["rules_skipped_manual"] > 0


@pytest.mark.skipif(not RULES.exists(), reason="catalogue not generated")
def test_drawing_only_never_hard_violation_on_noisy_rooms():
    p = FIX / "mimari.drawing_model.json"
    if not p.exists():
        pytest.skip("fixture missing")
    dm = json.loads(p.read_text(encoding="utf-8"))
    r = run_check(None, dm, {})
    assert not r["summary"]["errors"]
    assert r["summary"]["violation"] == 0
