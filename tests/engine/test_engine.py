import time

from builders import door, model, rect, slab, space, stair
from bimcheck.engine import diff_findings, run_check


def one(res, rid, key=None):
    fs = [f for f in res["findings"] if f["rule_id"] == rid and (key is None or f["id"].endswith(key))]
    assert fs, (rid, [f["id"] for f in res["findings"]])
    return fs[0]


def run(els, ctx=None, storeys=None, rules=None, **kw):
    return run_check(model(els, storeys), None, ctx or {}, rules, **kw)


def statuses(r):
    return {f["id"].split(":", 1)[1]: f["status"] for f in r["findings"]}


def test_declarative_height(mini_rules):
    els = [space("a", "bedroom", rect(0, 0, 3, 4), height=2.45),
           space("b", "bedroom", rect(5, 0, 8, 4), height=2.70),
           space("c", "bedroom", rect(9, 0, 12, 4), height=None)]
    r = run(els, rules=mini_rules, rule_ids=["KBB-28-4"])
    assert one(r, "KBB-28-4", ":a")["status"] == "review"  # within plausible exception (2.40)
    assert one(r, "KBB-28-4", ":a")["review_reason"] == "exception_may_apply"
    assert one(r, "KBB-28-4", ":b")["status"] == "pass"
    c = one(r, "KBB-28-4", ":c")
    assert c["status"] == "review" and c["review_reason"] == "missing_measure"
    els[0]["measures"]["height"] = 2.30
    assert one(run(els, rules=mini_rules, rule_ids=["KBB-28-4"]), "KBB-28-4", ":a")["status"] == "violation"
    els[0]["measures"]["height"] = 2.597  # unit tolerance edge
    assert one(run(els, rules=mini_rules, rule_ids=["KBB-28-4"]), "KBB-28-4", ":a")["status"] == "pass"


def test_override_disabled_and_misc(mini_rules):
    els = [space("a", "bedroom", rect(0, 0, 3, 4), height=2.45)]
    r = run(els, {"overrides": {"KBB-28-4": {"limit": 2.4}}}, rules=mini_rules, rule_ids=["KBB-28-4"])
    assert one(r, "KBB-28-4")["status"] == "pass"
    r = run(els, {"overrides": {"KBB-28-4": {"disabled": True}}}, rules=mini_rules, rule_ids=["KBB-28-4"])
    assert one(r, "KBB-28-4")["status"] == "not_applicable"
    r = run(els, rules=mini_rules)  # whole catalogue; never crashes, manual skipped, unknown custom -> review
    assert r["summary"]["rules_skipped_manual"] == 1 and not r["summary"]["errors"]
    assert one(r, "KBB-99-1")["status"] == "review"
    ids = [f["id"] for f in r["findings"]]
    assert len(ids) == len(set(ids))


def test_inferred_borderline_is_review(mini_rules):
    els = [space("a", "bedroom", rect(0, 0, 3, 4), height=2.61)]
    els[0]["provenance"]["height"] = "inferred"
    f = one(run(els, rules=mini_rules, rule_ids=["KBB-28-4"]), "KBB-28-4")
    assert f["status"] == "review" and f["review_reason"] == "low_confidence"


def test_finding_fields(mini_rules):
    els = [space("a", "bedroom", rect(0, 0, 3, 4), height=2.30)]
    f = one(run(els, rules=mini_rules, rule_ids=["KBB-28-4"]), "KBB-28-4")
    assert f["id"] == "KBB-28-4:a" and f["storey_name"] == "Ground" and f["anchor"]
    assert f["dimensions"] and f["dimensions"][0]["p2"][2] == 2.30
    assert f["highlight"][0]["role"] == "offending" and f["regulation_excerpt"] == "metin"
    assert f["message_en"] and f["message_tr"] and f["measured"]["value"] == 2.3


def test_room_min_dims(mini_rules):
    els = [space("lr", "living_room", rect(0, 0, 3.5, 4)),
           space("br1", "bedroom", rect(5, 0, 8, 4)),
           space("br2", "bedroom", rect(9, 0, 11, 4)),
           space("k", "kitchen", rect(0, 5, 1.2, 8)),
           space("w", "wc", rect(5, 5, 6.0, 6.2))]
    r = run(els, rules=mini_rules, rule_ids=["KBB-29-1"])
    assert statuses(r) == {"lr": "pass", "br1": "pass", "br2": "review", "k": "violation", "w": "pass"}
    assert one(r, "KBB-29-1", ":br2")["review_reason"] == "legal_judgement"
    assert one(r, "KBB-29-1", ":k")["dimensions"]


def test_door_dimensions(mini_rules):
    els = [door("d1", 0, 0, 0.90), door("d2", 3, 0, 0.80), door("d3", 6, 0, 0.90, height=2.0),
           door("d4", 9, 0, 1.0, is_entrance=True), door("wc", 12, 0, 0.8, space_guids=["WC"]),
           space("WC", "wc", rect(0, 5, 1.2, 6.5))]
    r = run(els, {"is_single_dwelling": False}, rules=mini_rules, rule_ids=["KBB-39-1"])
    st = statuses(r)
    assert st["d1"] == "pass" and st["d2"] == "violation" and st["d3"] == "violation"
    assert st["d4"] == "violation" and st["wc"] == "pass"
    assert one(r, "KBB-39-1", ":d1")["dimensions"]


def test_storey_height(mini_rules):
    st = [{"id": "S0", "name": "G", "elevation": 0, "height": 3.9, "is_underground": False},
          {"id": "S1", "name": "F", "elevation": 3.9, "height": 3.0, "is_underground": False},
          {"id": "S2", "name": "T", "elevation": 6.9, "height": None, "is_underground": False}]
    els = [space("a", "bedroom", rect(0, 0, 3, 4), sid="S0"), space("b", "bedroom", rect(0, 0, 3, 4), sid="S1"),
           space("c", "bedroom", rect(0, 0, 3, 4), sid="S2")]
    r = run(els, {"use": "residential"}, st, mini_rules, rule_ids=["KBB-28-1"])
    assert one(r, "KBB-28-1", ":S0")["status"] == "review"
    assert one(r, "KBB-28-1", ":S1")["status"] == "pass"
    assert one(r, "KBB-28-1", "skipped-storeys")["status"] == "not_applicable"
    st[0]["elevation"], st[1]["elevation"] = 0, 5.0
    st[2]["elevation"] = 8.0
    els += [space("d", "bedroom", rect(0, 0, 3, 4), sid="S1")]
    r = run(els, {"use": "residential"}, st, mini_rules, rule_ids=["KBB-28-1"])
    assert one(r, "KBB-28-1", ":S0")["status"] in ("violation", "review")


def test_stairs(mini_rules):
    els = [stair("s1", 0.17, 0.28), stair("s2", 0.15, 0.30), stair("s3", 0.20, 0.25, width=0.9)]
    ids = ["KBB-31-2a", "KBB-31-2b", "KBB-31-1"]
    r = run(els, {"use": "residential"}, rules=mini_rules, rule_ids=ids)
    assert one(r, "KBB-31-2a", ":s1")["status"] == "review"
    assert one(r, "KBB-31-2a", ":s3")["status"] == "violation"
    assert one(r, "KBB-31-2b", ":s1")["status"] == "pass"       # 2*.17+.28 = .62
    assert one(r, "KBB-31-2b", ":s3")["status"] == "violation"  # tread .25 and formula .65
    assert one(r, "KBB-31-1", ":s3")["status"] == "violation"
    assert one(r, "KBB-31-1", ":s1")["status"] == "pass"
    r = run(els, {"use": "residential", "has_elevator": True}, rules=mini_rules, rule_ids=["KBB-31-2a"])
    assert one(r, "KBB-31-2a", ":s1")["status"] == "pass"
    r = run(els, {"use": "residential", "has_elevator": False}, rules=mini_rules, rule_ids=["KBB-31-2a"])
    assert one(r, "KBB-31-2a", ":s1")["status"] == "violation"


def test_exterior_light(mini_rules):
    els = [space("a", "bedroom", rect(0, 0, 3, 4), has_exterior_window=False),
           space("b", "living_room", rect(5, 0, 9, 4), has_exterior_window=None),
           space("c", "bedroom", rect(9, 0, 12, 4))]
    st = statuses(run(els, rules=mini_rules, rule_ids=["KBB-32-1"]))
    assert st == {"a": "violation", "b": "review", "c": "pass"}


def test_elevator(mini_rules):
    def storeys(n):
        return [{"id": f"S{i}", "name": f"L{i}", "elevation": 3.0 * i, "height": 3.0, "is_underground": False}
                for i in range(n)]
    els = lambda n: [space(f"s{i}", "bedroom", rect(0, 0, 3, 4), sid=f"S{i}") for i in range(n)]
    r = run(els(4), {}, storeys(4), mini_rules, rule_ids=["KBB-34-1"])
    assert one(r, "KBB-34-1")["status"] == "review"
    r = run(els(4), {"has_elevator": False}, storeys(4), mini_rules, rule_ids=["KBB-34-1"])
    assert one(r, "KBB-34-1")["status"] == "violation"
    r = run(els(4), {"has_elevator": True}, storeys(4), mini_rules, rule_ids=["KBB-34-1"])
    assert one(r, "KBB-34-1")["status"] == "pass"
    r = run(els(4), {"is_single_dwelling": True}, storeys(4), mini_rules, rule_ids=["KBB-34-1"])
    assert one(r, "KBB-34-1")["status"] == "not_applicable"
    r = run(els(2), {}, storeys(2), mini_rules, rule_ids=["KBB-34-1"])
    assert one(r, "KBB-34-1")["status"] == "not_applicable"


def _site_model():
    return [slab("sl", 5, 5, 15, 15), space("a", "bedroom", rect(5.3, 5.3, 14.7, 14.7)),
            slab("sl1", 5, 5, 15, 15, sid="S1", z=3.0), space("b", "bedroom", rect(5.3, 5.3, 14.7, 14.7), sid="S1", z=3.0)]


def test_setbacks_and_taks_kaks(mini_rules):
    parcel = rect(0, 0, 20, 20)
    ids = ["KBB-23-1", "KBB-21-1", "KBB-25-1"]
    ctx = {"parcel_polygon": parcel, "front_edge_index": 0, "taks": 0.40, "kaks": 1.60, "max_storeys": 2}
    r = run(_site_model(), ctx, rules=mini_rules, rule_ids=ids)
    st = statuses(r)
    assert st["parcel:e0"] == "review"      # exactly at the 5.0 m limit with an estimated footprint -> borderline
    assert st["parcel:e1"] == "pass" and st["parcel:e2"] == "pass"
    close = [slab("sl", 2, 5, 15, 15), space("a", "bedroom", rect(2.3, 5.3, 14.7, 14.7))]
    r2 = run(close, ctx, rules=mini_rules, rule_ids=["KBB-23-1"])
    assert statuses(r2)["parcel:e3"] == "violation"  # edge 3 is x=0: 2 m < 3 m side setback
    assert one(r, "KBB-21-1", "taks")["status"] in ("pass", "review")
    assert one(r, "KBB-21-1", "kaks")["status"] in ("pass", "review")
    assert one(r, "KBB-25-1")["status"] == "pass"
    f = one(r, "KBB-23-1", ":parcel:e0")
    assert f["dimensions"] and f["dimensions"][0]["label"].endswith("m")
    # no front edge -> review unless clearly fine/clearly violating
    ctx2 = dict(ctx, front_edge_index=None, parcel_polygon=rect(0, 0, 14, 20))
    r = run(_site_model(), ctx2, rules=mini_rules, rule_ids=["KBB-23-1"])
    assert any(f["status"] == "violation" for f in r["findings"])
    # missing context -> review not crash
    r = run(_site_model(), {}, rules=mini_rules, rule_ids=ids)
    assert one(r, "KBB-23-1")["review_reason"] == "missing_context"


def test_diff_and_performance(mini_rules):
    a = run([space("a", "bedroom", rect(0, 0, 3, 4), height=2.3)], rules=mini_rules, rule_ids=["KBB-28-4"])
    b = run([space("a", "bedroom", rect(0, 0, 3, 4), height=2.7)], rules=mini_rules, rule_ids=["KBB-28-4"])
    d = diff_findings(a, b)
    assert [f["id"] for f in d["resolved"]] == ["KBB-28-4:a"] and not d["new"]
    d = diff_findings(b, a)
    assert [f["id"] for f in d["new"]] == ["KBB-28-4:a"]
    t = time.time()
    run(_site_model() * 20, rules=mini_rules)
    assert time.time() - t < 2
