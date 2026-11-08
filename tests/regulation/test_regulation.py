import json
from pathlib import Path

from bimcheck.regulation.catalogue import get_rule, load_articles, load_rules, validate_catalogue
from bimcheck.regulation.extract import classify_colour

ROOT = Path(__file__).resolve().parents[2]


def test_catalogue_valid():
    cat = load_rules()
    assert validate_catalogue(cat) == []
    assert len(cat["rules"]) >= 60


def test_validator_catches_problems():
    cat = load_rules()
    cat["rules"].append(dict(cat["rules"][0]))
    cat["rules"][0]["check"]["measure"] = "bogus"
    cat["rules"][1]["check"]["custom_id"] = "nope"
    errs = validate_catalogue(cat)
    assert any("duplicate" in e for e in errs)
    assert any("custom_id" in e for e in errs) or any("measure" in e for e in errs)


def lim(rid, key="limit"):
    return get_rule(rid)["check"][key]


def test_key_limits():
    assert lim("KBB-28-4") == 2.60 and get_rule("KBB-28-4")["automation"] == "auto"
    assert lim("KBB-28-5") == 2.20 and lim("KBB-28-6") == 2.20
    assert lim("KBB-29-3") == 1.20
    assert lim("KBB-30-1") == 1.5 and get_rule("KBB-30-1")["check"]["extra"]["public_limit"] == 2.20
    assert get_rule("KBB-28-1-a")["check"]["extra"]["ground_with_mezzanine"] == 6.5
    assert get_rule("KBB-28-1-c")["check"]["extra"]["upper"] == 3.6
    e = get_rule("KBB-31-2-a")["check"]["extra"]
    assert (e["limit_without_elevator"], e["limit_with_elevator"], e["limit_external"]) == (0.16, 0.18, 0.15)
    assert get_rule("KBB-31-2-b")["check"]["extra"]["min_tread"] == 0.27
    assert lim("KBB-38-1-railing") == 1.10
    assert lim("KBB-39-1-a") == 2.10 and lim("KBB-39-1-b") == 1.50
    e = get_rule("KBB-39-1-c")["check"]["extra"]
    assert (e["unit_entrance"], e["other"], e["balcony_wc"]) == (1.00, 0.90, 0.80)
    assert lim("KBB-23-1-a") == 5.0 and lim("KBB-23-1-b") == 3.0 and lim("KBB-23-1-c") == 3.0
    assert lim("KBB-23-1-cc") == 0.5
    assert lim("KBB-32-2-a") == 1.5 and lim("KBB-32-2-b") == 2.0 and lim("KBB-32-3") == 0.6
    assert lim("KBB-43-1") == 0.5


def test_text_is_current_in_force():
    r = get_rule("KBB-28-4")
    assert "2.60" in r["text_tr"]
    t = get_rule("KBB-28-1-a")["text_tr"]
    assert "6.50" in t and "5.50" not in t
    assert get_rule("KBB-28-1-a")["revision"]["status"] == "amended"
    arts = {a["article"]: a for a in load_articles()}
    p4 = {p["no"]: p for p in arts[6]["paragraphs"]}["4"]["text"]
    assert "1500" in p4 and "2000" not in p4
    assert "120" in json.dumps(arts[22], ensure_ascii=False)
    assert "15" == arts[9]["paragraphs"][0]["items"][0]["tables"][0]["rows"][-1][1]


def test_tables_and_structure():
    arts = {a["article"]: a for a in load_articles()}
    t = arts[29]["paragraphs"][0]["tables"][0]
    assert t["rows"][0] == ["1 oturma odası", "3.00 metre", "12.0 m²"]
    assert arts[30]["paragraphs"][11]["tables"][0]["rows"][0][1].startswith("1:12")
    assert len(arts[28]["paragraphs"]) == 7 and len(arts[34]["paragraphs"]) == 11
    assert [i["key"] for i in arts[28]["paragraphs"][0]["items"]] == ["a", "b", "c", "ç", "d"]


def test_colour_classification():
    assert classify_colour(0x808080) == "deleted" and classify_colour(0xA6A6A6) == "deleted"
    assert classify_colour(0xFF0000) == "added"
    assert classify_colour(0x000000) == "kept" and classify_colour(0x0070C0) == "kept"


def test_extraction_reproducible(tmp_path):
    from bimcheck.regulation.extract import write_outputs
    arts, warns = write_outputs(out_json=tmp_path / "a.json", out_md=tmp_path / "a.md")
    assert warns == []
    assert json.loads((tmp_path / "a.json").read_text(encoding="utf-8")) == json.loads((ROOT / "regulation" / "articles.json").read_text(encoding="utf-8"))
