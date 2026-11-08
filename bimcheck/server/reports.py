"""Report generators: CSV and standalone printable HTML (JSON is just the merged findings)."""
from __future__ import annotations

import csv
import html
import io
from datetime import datetime

DECISION_LABEL = {
    "accepted_violation": "Violation accepted",
    "waived": "Waived",
    "compliant": "Marked compliant",
    "needs_info": "Needs info",
}
STATUS_ORDER = {"violation": 0, "review": 1, "pass": 2, "not_applicable": 3}


def select(findings: list[dict], include_all: bool = False, statuses: set[str] | None = None) -> list[dict]:
    if statuses:
        sel = [f for f in findings if f.get("status") in statuses]
    elif include_all:
        sel = list(findings)
    else:
        sel = [f for f in findings if f.get("status") in ("violation", "review")]
    sel.sort(key=lambda f: (STATUS_ORDER.get(f.get("status"), 9), f.get("article") or 0, str(f.get("paragraph") or ""), f.get("id", "")))
    return sel


def _fmt_val(m: dict | None) -> str:
    if not m or m.get("value") is None:
        return ""
    v = m["value"]
    if isinstance(v, float):
        v = f"{v:.3f}".rstrip("0").rstrip(".")
    return f"{v} {m.get('unit') or ''}".strip()


def _fmt_req(r: dict | None) -> str:
    if not r or r.get("value") is None:
        return ""
    v = r["value"]
    if isinstance(v, float):
        v = f"{v:.3f}".rstrip("0").rstrip(".")
    return f"{r.get('op') or ''} {v} {r.get('unit') or ''}".strip()


def to_csv(findings: list[dict]) -> bytes:
    buf = io.StringIO()
    w = csv.writer(buf, lineterminator="\r\n")
    w.writerow(["id", "status", "decision", "note", "rule_id", "article", "paragraph", "category", "severity", "storey",
                "title_en", "title_tr", "message_en", "measured", "provenance", "required", "review_reason",
                "review_hint", "elements", "source"])
    for f in findings:
        d = f.get("decision") or {}
        w.writerow([
            f.get("id"), f.get("status"), d.get("decision", ""), d.get("note", ""), f.get("rule_id"), f.get("article"),
            f.get("paragraph"), f.get("category"), f.get("severity"), f.get("storey_name") or "",
            f.get("title_en"), f.get("title_tr"), f.get("message_en"), _fmt_val(f.get("measured")),
            (f.get("measured") or {}).get("provenance") or "", _fmt_req(f.get("required")), f.get("review_reason") or "",
            f.get("review_hint") or "", ";".join(f.get("element_guids") or []), f.get("source") or "",
        ])
    return ("﻿" + buf.getvalue()).encode("utf-8")


_CSS = """
:root{--bg:#fff;--fg:#1b2430;--mut:#667085;--line:#d8dee8;--red:#c0392b;--amb:#b7791f;--grn:#2f855a;--blu:#2b6cb0}
*{box-sizing:border-box}body{font:14px/1.5 -apple-system,Segoe UI,Roboto,sans-serif;color:var(--fg);background:var(--bg);margin:0;padding:32px;max-width:980px;margin:auto}
h1{margin:0 0 4px;font-size:24px}h2{margin:28px 0 8px;font-size:17px;border-bottom:2px solid var(--line);padding-bottom:4px}
.meta{color:var(--mut);margin-bottom:16px}table.sum{border-collapse:collapse;margin:8px 0 16px}table.sum td,table.sum th{border:1px solid var(--line);padding:4px 12px;text-align:left}
.f{border:1px solid var(--line);border-left:6px solid var(--mut);border-radius:6px;padding:12px 14px;margin:10px 0;break-inside:avoid}
.f.violation{border-left-color:var(--red)}.f.review{border-left-color:var(--amb)}.f.pass{border-left-color:var(--grn)}
.f h3{margin:0 0 4px;font-size:15px}.f .sub{color:var(--mut);font-size:12px}
.chip{display:inline-block;padding:1px 8px;border-radius:10px;font-size:11px;font-weight:600;color:#fff;background:var(--mut);margin-right:6px;text-transform:uppercase;letter-spacing:.03em}
.chip.violation{background:var(--red)}.chip.review{background:var(--amb)}.chip.pass{background:var(--grn)}.chip.dec{background:var(--blu)}
blockquote{margin:8px 0;padding:6px 12px;background:#f5f7fa;border-left:3px solid var(--line);color:#344054;font-size:13px;white-space:pre-wrap}
.kv{display:grid;grid-template-columns:140px 1fr;gap:2px 10px;font-size:13px;margin:6px 0}.kv b{color:var(--mut);font-weight:600}
.dec{background:#ebf4ff;border:1px solid #bee3f8;border-radius:6px;padding:6px 10px;margin-top:8px}
footer{margin-top:32px;color:var(--mut);font-size:12px}
@media print{body{padding:0}.f{page-break-inside:avoid}}
"""


def _e(x) -> str:
    return html.escape("" if x is None else str(x))


def to_html(project: dict, findings: list[dict], all_findings: list[dict], summary: dict | None) -> bytes:
    counts: dict[str, int] = {}
    for f in all_findings:
        counts[f.get("status", "?")] = counts.get(f.get("status", "?"), 0) + 1
    decided = sum(1 for f in all_findings if f.get("decision") and f["status"] in ("violation", "review"))
    open_items = sum(1 for f in all_findings if f["status"] in ("violation", "review"))
    parts = [f"<!doctype html><html lang='en'><head><meta charset='utf-8'><title>BIMCheck report - {_e(project.get('name'))}</title>"
             f"<meta name='viewport' content='width=device-width,initial-scale=1'><style>{_CSS}</style></head><body>",
             f"<h1>BIMCheck compliance report</h1><div class='meta'>Project <b>{_e(project.get('name'))}</b> &middot; "
             f"model: {_e((project.get('model') or {}).get('file') or '-')} &middot; drawing: "
             f"{_e((project.get('drawing') or {}).get('file') or '-')} &middot; generated {datetime.now().strftime('%Y-%m-%d %H:%M')}</div>",
             "<table class='sum'><tr><th>Violations</th><th>Needs review</th><th>Pass</th><th>Decided</th></tr>"
             f"<tr><td>{counts.get('violation', 0)}</td><td>{counts.get('review', 0)}</td><td>{counts.get('pass', 0)}</td>"
             f"<td>{decided} / {open_items}</td></tr></table>"]
    if summary and summary.get("errors"):
        parts.append("<p><b>Engine errors:</b> " + _e("; ".join(summary["errors"])) + "</p>")
    cur = None
    for f in findings:
        if f.get("status") != cur:
            cur = f.get("status")
            parts.append(f"<h2>{_e(str(cur).replace('_', ' ').title())}</h2>")
        d = f.get("decision")
        art = f"Art. {f.get('article')}" + (f"/{f.get('paragraph')}" if f.get("paragraph") else "")
        parts.append(f"<div class='f {_e(f.get('status'))}'><h3><span class='chip {_e(f.get('status'))}'>{_e(f.get('status'))}</span>"
                     f"{_e(f.get('title_en') or f.get('title_tr'))}</h3>"
                     f"<div class='sub'>{_e(art)} &middot; {_e(f.get('category'))} &middot; {_e(f.get('storey_name') or 'no storey')}"
                     f" &middot; {_e(f.get('rule_id'))}</div><p>{_e(f.get('message_en') or f.get('message_tr'))}</p>")
        kv = []
        if f.get("measured") and f["measured"].get("value") is not None:
            kv.append(("Measured", f"{_fmt_val(f['measured'])} ({f['measured'].get('provenance') or 'n/a'})"))
        if f.get("required") and f["required"].get("value") is not None:
            kv.append(("Required", _fmt_req(f["required"])))
        if f.get("review_reason"):
            kv.append(("Review reason", f["review_reason"]))
        if f.get("review_hint"):
            kv.append(("Check", f["review_hint"]))
        if f.get("element_guids"):
            kv.append(("Elements", ", ".join(f["element_guids"][:8]) + (" ..." if len(f["element_guids"]) > 8 else "")))
        if kv:
            parts.append("<div class='kv'>" + "".join(f"<b>{_e(k)}</b><span>{_e(v)}</span>" for k, v in kv) + "</div>")
        if f.get("regulation_excerpt"):
            parts.append(f"<blockquote>{_e(f['regulation_excerpt'])}</blockquote>")
        if d:
            parts.append(f"<div class='dec'><span class='chip dec'>{_e(DECISION_LABEL.get(d.get('decision'), d.get('decision')))}</span>"
                         f"{_e(d.get('note') or '')} <span class='sub'>&mdash; {_e(d.get('by'))}, {_e(d.get('at'))}</span></div>")
        else:
            parts.append("<div class='sub'>No decision recorded.</div>")
        parts.append("</div>")
    if not findings:
        parts.append("<p>No findings.</p>")
    parts.append("<footer>Generated by BIMCheck. Automated results are advisory; decisions marked above were taken by a human reviewer.</footer></body></html>")
    return "".join(parts).encode("utf-8")
