import io
import json
import sys
import xml.dom.minidom as md
import zipfile
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).parent))
from stub_backend import FIX, StubBackend  # noqa: E402

from bimcheck.server.app import create_app  # noqa: E402


@pytest.fixture()
def client(tmp_path):
    app = create_app(data_dir=tmp_path, backend=StubBackend())
    with TestClient(app) as c:
        yield c


def _ifc():
    return {"file": ("house.ifc", (FIX / "house.ifc").read_bytes(), "application/octet-stream")}


@pytest.fixture()
def pid(client):
    r = client.post("/api/projects", json={"name": "Test"})
    assert r.status_code == 200
    return r.json()["id"]


@pytest.fixture()
def loaded(client, pid):
    r = client.post(f"/api/projects/{pid}/model", files=_ifc())
    assert r.status_code == 200, r.text
    return pid


def test_health_and_static(client):
    assert client.get("/api/health").json()["ok"] is True
    r = client.get("/")
    assert r.status_code == 200 and "BIMCheck" in r.text
    js = client.get("/js/app.js")
    assert js.status_code == 200 and "javascript" in js.headers["content-type"]


def test_project_crud(client):
    p = client.post("/api/projects", json={"name": "Alpha"}).json()
    assert client.get("/api/projects").json()[0]["id"] == p["id"]
    assert client.get(f"/api/projects/{p['id']}").json()["name"] == "Alpha"
    assert client.get("/api/projects/nope").status_code == 404
    assert client.get("/api/projects/bad.id").status_code == 404
    assert client.delete(f"/api/projects/{p['id']}").status_code == 200
    assert client.get(f"/api/projects/{p['id']}").status_code == 404


def test_upload_model_pipeline(client, pid):
    with client.websocket_connect(f"/ws/projects/{pid}") as ws:
        assert ws.receive_json()["type"] == "hello"
        r = client.post(f"/api/projects/{pid}/model", files=_ifc())
        assert r.status_code == 200
        body = r.json()
        assert body["model"]["file"] == "house.ifc" and len(body["model"]["storeys"]) == 2
        assert body["has_glb"] and body["model_version"] == 1
        assert body["summary"]["violation"] >= 1
        types = []
        while True:
            ev = ws.receive_json()
            types.append(ev["type"])
            if ev["type"] == "model_updated":
                break
        assert "status" in types and ev["diff"]["initial"] is True
    assert client.get(f"/api/projects/{pid}/geometry.glb").content[:4] == b"glTF"
    assert client.get(f"/api/projects/{pid}/building-model").json()["elements"]
    f = client.get(f"/api/projects/{pid}/findings").json()
    assert len(f["findings"]) == 5 and f["summary"]["undecided"] == 4


def test_bad_uploads(client, pid):
    r = client.post(f"/api/projects/{pid}/model", files={"file": ("x.txt", b"hello", "text/plain")})
    assert r.status_code == 400 and "unsupported" in r.json()["detail"]
    r = client.post(f"/api/projects/{pid}/model", files={"file": ("x.ifc", b"not an ifc", "text/plain")})
    assert r.status_code == 400 and "valid IFC" in r.json()["detail"]
    r = client.post(f"/api/projects/{pid}/model", files={"file": ("x.ifc", b"", "text/plain")})
    assert r.status_code == 400
    r = client.post(f"/api/projects/{pid}/model", files={"file": ("x.ifc", b"ISO-10303-21;\nBROKEN", "text/plain")})
    assert r.status_code == 400 and "corrupt" in r.json()["detail"]
    r = client.post(f"/api/projects/{pid}/drawing", files={"file": ("x.dwg", b"zzzz", "x/y")})
    assert r.status_code == 400
    assert client.post("/api/projects/nope/model", files=_ifc()).status_code == 404
    # nothing was ingested
    assert client.get(f"/api/projects/{pid}/building-model").status_code == 404
    assert client.get(f"/api/projects/{pid}/geometry.glb").status_code == 404


def test_decisions_survive_recheck(client, loaded):
    pid = loaded
    fid = "KBB-28-4:" + json.loads((FIX / "house.findings.json").read_text())["findings"][0]["element_guids"][0]
    r = client.put(f"/api/projects/{pid}/findings/{fid}/decision", json={"decision": "waived", "note": "ok by municipality"})
    assert r.status_code == 200 and r.json()["decision"]["decision"] == "waived"
    assert client.put(f"/api/projects/{pid}/findings/{fid}/decision", json={"decision": "bogus"}).status_code == 400
    r = client.put(f"/api/projects/{pid}/rule-overrides", json={"KBB-28-4": {"limit": 2.4}})
    assert r.status_code == 200
    assert r.json()["diff"]["counts"]["resolved"] == 1
    f = {x["id"]: x for x in client.get(f"/api/projects/{pid}/findings").json()["findings"]}
    assert f[fid]["status"] == "pass" and f[fid]["decision"]["note"] == "ok by municipality"
    client.put(f"/api/projects/{pid}/findings/{fid}/decision", json={"decision": None})
    assert client.get(f"/api/projects/{pid}/findings").json()["findings"][0]["decision"] is None


def test_context_roundtrip_and_derive(client, loaded):
    pid = loaded
    r = client.put(f"/api/projects/{pid}/context", json={"use": "residential", "taks": 0.4, "overrides": {"KBB-1-1": {"limit": 1}}})
    assert r.status_code == 200
    ctx = client.get(f"/api/projects/{pid}/context").json()
    assert ctx["taks"] == 0.4 and ctx["overrides"]["KBB-1-1"]["limit"] == 1
    assert client.get(f"/api/projects/{pid}/context/derive").json()["warnings"]
    r = client.post(f"/api/projects/{pid}/drawing", files={"file": ("plan.dxf", (FIX / "plan.dxf").read_bytes(), "x/y")})
    assert r.status_code == 200 and r.json()["drawing"]["has_parcel"]
    d = client.get(f"/api/projects/{pid}/context/derive").json()
    assert d["context"]["parcel_area"] == 400.0 and d["context"]["taks"] == 0.2
    assert client.get(f"/api/projects/{pid}/drawing-model").json()["parcel"]


def test_reports(client, loaded):
    pid = loaded
    fid = client.get(f"/api/projects/{pid}/findings").json()["findings"][0]["id"]
    client.put(f"/api/projects/{pid}/findings/{fid}/decision", json={"decision": "accepted_violation", "note": "needs <fix>"})
    j = client.get(f"/api/projects/{pid}/report.json").json()
    assert len(j["findings"]) == 5
    c = client.get(f"/api/projects/{pid}/report.csv")
    assert c.content.startswith(b"\xef\xbb\xbf") and b"accepted_violation" in c.content
    assert len(c.text.strip().splitlines()) == 1 + 4
    h = client.get(f"/api/projects/{pid}/report.html").text
    assert "<!doctype html>" in h and "needs &lt;fix&gt;" in h and "Konut yapilarinda" in h
    assert "<script" not in h
    b = client.get(f"/api/projects/{pid}/report.bcf")
    z = zipfile.ZipFile(io.BytesIO(b.content))
    names = z.namelist()
    assert "bcf.version" in names and sum(n.endswith("markup.bcf") for n in names) == 4
    vp = next(z.read(n).decode() for n in names if n.endswith(".bcfv"))
    assert "PerspectiveCamera" in vp and "IfcGuid" in vp
    for n in names:
        if n.endswith((".bcf", ".bcfv", ".bcfp", ".version")):
            md.parseString(z.read(n))
    assert client.get(f"/api/projects/{pid}/report.pdf").status_code == 404


def test_regulation_and_samples(client):
    assert client.get("/api/rules").json()["rules"]
    assert client.get("/api/regulation/articles").json()[0]["article"] == 28
    assert client.get("/api/regulation/articles/28").json()["paragraphs"]
    assert client.get("/api/regulation/articles/9999").status_code == 404
    assert client.get("/api/samples/..%2Fpyproject.toml").status_code == 404
    names = [s["name"] for s in client.get("/api/samples").json()]
    assert "Duplex_A_20110907.ifc" in names
    assert client.get("/api/samples/AC20-FZK-Haus.ifc").status_code == 200


def test_ws_decision_event(client, loaded):
    pid = loaded
    with client.websocket_connect(f"/ws/projects/{pid}") as ws:
        ws.receive_json()
        client.put(f"/api/projects/{pid}/findings/KBB-23-1:parcel/decision", json={"decision": "needs_info"})
        ev = ws.receive_json()
        assert ev["type"] == "decision_updated" and ev["decision"]["decision"] == "needs_info"
