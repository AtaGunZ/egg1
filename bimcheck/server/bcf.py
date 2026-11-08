"""BCF 2.1 export: one topic per violation/review finding, with a viewpoint (camera, selection, colouring, lines)."""
from __future__ import annotations

import io
import math
import uuid
import zipfile
from xml.sax.saxutils import escape

from .store import now_iso

NS = uuid.UUID("6f1c2a3e-8a52-4a52-9d64-b1a1b0c0dec0")
DEC_STATUS = {"accepted_violation": "Closed", "waived": "Closed", "compliant": "Closed", "needs_info": "Open"}


def _guid(*parts: str) -> str:
    return str(uuid.uuid5(NS, "|".join(parts)))


def _vec(v):
    return [float(x) for x in v]


def _norm(v):
    n = math.sqrt(sum(c * c for c in v)) or 1.0
    return [c / n for c in v]


def _camera(finding: dict, elements: dict[str, dict], bounds: tuple[list, list] | None):
    pts_min, pts_max = None, None
    for h in finding.get("highlight") or []:
        e = elements.get(h.get("guid"))
        if e and e.get("bbox"):
            lo, hi = e["bbox"]["min"], e["bbox"]["max"]
            pts_min = lo if pts_min is None else [min(a, b) for a, b in zip(pts_min, lo)]
            pts_max = hi if pts_max is None else [max(a, b) for a, b in zip(pts_max, hi)]
    if pts_min is None and finding.get("anchor"):
        a = _vec(finding["anchor"])
        pts_min, pts_max = [c - 1 for c in a], [c + 1 for c in a]
    if pts_min is None and bounds:
        pts_min, pts_max = bounds
    if pts_min is None:
        return None
    c = [(a + b) / 2 for a, b in zip(pts_min, pts_max)]
    diag = math.sqrt(sum((b - a) ** 2 for a, b in zip(pts_min, pts_max))) or 2.0
    dist = max(diag * 1.6, 4.0)
    d = _norm([0.6, 0.8, -0.6])  # looking from SW-ish above: camera at c - d*dist
    pos = [c[i] - d[i] * dist for i in range(3)]
    up = [0, 0, 1]
    dot = sum(up[i] * d[i] for i in range(3))
    up = _norm([up[i] - dot * d[i] for i in range(3)])
    return pos, d, up


def _xyz(tag: str, v) -> str:
    return f"<{tag}><X>{v[0]:.4f}</X><Y>{v[1]:.4f}</Y><Z>{v[2]:.4f}</Z></{tag}>"


def _viewpoint_xml(finding: dict, elements: dict[str, dict], bounds) -> str:
    hl = finding.get("highlight") or [{"guid": g, "role": "offending"} for g in finding.get("element_guids") or []]
    comp = lambda g: f'<Component IfcGuid="{escape(g)}"/>'  # noqa: E731
    off = [h["guid"] for h in hl if h.get("role") != "context"]
    ctx = [h["guid"] for h in hl if h.get("role") == "context"]
    x = ['<?xml version="1.0" encoding="UTF-8"?>\n<VisualizationInfo Guid="%s">' % _guid(finding["id"], "vp")]
    x.append("<Components>")
    if hl:
        x.append("<Selection>" + "".join(comp(g) for g in off or ctx) + "</Selection>")
    x.append('<Visibility DefaultVisibility="true"/>')
    if hl:
        x.append("<Coloring>")
        if off:
            x.append('<Color Color="FFE53935">' + "".join(comp(g) for g in off) + "</Color>")
        if ctx:
            x.append('<Color Color="FFFFB300">' + "".join(comp(g) for g in ctx) + "</Color>")
        x.append("</Coloring>")
    x.append("</Components>")
    cam = _camera(finding, elements, bounds)
    if cam:
        pos, d, up = cam
        x.append("<PerspectiveCamera>" + _xyz("CameraViewPoint", pos) + _xyz("CameraDirection", d) + _xyz("CameraUpVector", up)
                 + "<FieldOfView>60</FieldOfView></PerspectiveCamera>")
    dims = finding.get("dimensions") or []
    if dims:
        x.append("<Lines>" + "".join(
            "<Line>" + _xyz("StartPoint", _vec(dm["p1"])) + _xyz("EndPoint", _vec(dm["p2"])) + "</Line>"
            for dm in dims if dm.get("p1") and dm.get("p2")) + "</Lines>")
    x.append("</VisualizationInfo>")
    return "".join(x)


def build_bcf(project: dict, findings: list[dict], building_model: dict | None) -> bytes:
    elements = {e["guid"]: e for e in (building_model or {}).get("elements", []) if e.get("guid")}
    bounds = None
    boxes = [e["bbox"] for e in elements.values() if e.get("bbox")]
    if boxes:
        bounds = ([min(b["min"][i] for b in boxes) for i in range(3)], [max(b["max"][i] for b in boxes) for i in range(3)])
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("bcf.version", '<?xml version="1.0" encoding="UTF-8"?>\n<Version VersionId="2.1"><DetailedVersion>2.1</DetailedVersion></Version>')
        z.writestr("project.bcfp", '<?xml version="1.0" encoding="UTF-8"?>\n<ProjectExtension><Project ProjectId="%s"><Name>%s</Name></Project>'
                   "<ExtensionSchema></ExtensionSchema></ProjectExtension>" % (escape(project["id"]), escape(project.get("name") or "")))
        ifc_file = (project.get("model") or {}).get("file") or ""
        for f in findings:
            tg = _guid(project["id"], f["id"])
            vpg = _guid(f["id"], "vp")
            dec = f.get("decision")
            status = DEC_STATUS.get(dec["decision"], "Open") if dec else "Open"
            prio = {"error": "High", "warning": "Normal", "info": "Low"}.get(f.get("severity"), "Normal")
            desc = (f.get("message_en") or "") + "\n"
            if f.get("review_hint"):
                desc += f"Check: {f['review_hint']}\n"
            if f.get("regulation_excerpt"):
                desc += f"Regulation (Art. {f.get('article')}/{f.get('paragraph')}): {f['regulation_excerpt']}"
            labels = "".join(f"<Labels>{escape(str(l))}</Labels>" for l in (f.get("category"), f"Art.{f.get('article')}") if l)
            comments = ""
            if dec:
                comments = (f'<Comment Guid="{_guid(f["id"], "c")}"><Date>{escape(dec["at"])}</Date><Author>{escape(dec.get("by") or "reviewer")}</Author>'
                            f'<Comment>{escape(dec["decision"] + ": " + (dec.get("note") or ""))}</Comment><Viewpoint Guid="{vpg}"/></Comment>')
            markup = (f'<?xml version="1.0" encoding="UTF-8"?>\n<Markup>'
                      f'<Header><File IsExternal="false"><Filename>{escape(ifc_file)}</Filename></File></Header>'
                      f'<Topic Guid="{tg}" TopicType="{"Violation" if f["status"] == "violation" else "Review"}" TopicStatus="{status}">'
                      f'<Title>{escape((f.get("title_en") or f.get("rule_id") or "") + " - " + (f.get("storey_name") or ""))}</Title>'
                      f'<Priority>{prio}</Priority>{labels}<CreationDate>{now_iso()}</CreationDate><CreationAuthor>BIMCheck</CreationAuthor>'
                      f'<Description>{escape(desc)}</Description></Topic>{comments}'
                      f'<Viewpoints Guid="{vpg}"><Viewpoint>viewpoint.bcfv</Viewpoint></Viewpoints></Markup>')
            z.writestr(f"{tg}/markup.bcf", markup)
            z.writestr(f"{tg}/viewpoint.bcfv", _viewpoint_xml(f, elements, bounds))
    return buf.getvalue()
