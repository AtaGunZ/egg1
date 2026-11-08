"""S1 regulation pipeline: redline PDF -> current-in-force articles.

The Kayseri regulation PDF is a *redline* ("lejantli"). The legend on page 1 reads
    blue  (0x0070C0) = "Degistirilemeyen metin"  (upper-regulation text that may not be changed) -> kept
    black (0x000000) = "mevcut korunan metin"     -> kept
    red   (0xFF0000) = "eklenen metin"            -> ADDED   (part of the current text)
    grey  (0x808080) = "cikartilan metin"         -> DELETED (NOT part of the current text)
The real colour values found in the PDF are listed by `colour_census` (also written to
regulation/extract_report.json).  A near-grey 0xA6A6A6 occurs (page 3, "40.00" -> deleted) and the rare
0x7030A0 / 0x00B050 values only colour whitespace, so classification works on *ranges*, not exact values.

Pipeline
  1. read_rows(pdf)          page -> rows of colour-classified segments (reading order, same-baseline cells merged)
  2. build_articles(...)     MADDE n -> paragraphs "(1)" -> items "a)" (or "(a)") -> sub-items "1)"; revisions
  3. regulation/overrides.json   hand-curated tables (Madde 9, 29, 30) + "tail" routing; verified against PDF text
  4. write_outputs()         regulation/articles.json, regulation/articles_redline.md, regulation/extract_report.json

Run:  python -m bimcheck.regulation.extract
"""
from __future__ import annotations

import json
import re
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
PDF_PATH = ROOT / "regulation" / "kayseri-imar-yonetmeligi-2022-lejantli.pdf"
OUT_ARTICLES = ROOT / "regulation" / "articles.json"
OUT_REDLINE = ROOT / "regulation" / "articles_redline.md"
OVERRIDES = ROOT / "regulation" / "overrides.json"

KEPT, ADDED, DELETED, WS = "kept", "added", "deleted", "ws"
BODY_LAST_PAGE = 28  # pages 29+ are annex forms (EK-1 ...): no design limits in them

# Turkish alphabet order used for item letters (a b c ç d e f g ğ h ı i j k l m n o ö p r s ş t u ü v y z)
TR_LETTERS = list("abcçdefgğhıijklmnoöprsştuüvyz")
LETTER_ORDER = {ch: i for i, ch in enumerate(TR_LETTERS)}


def classify_colour(rgb: int) -> str:
    """Classify a span colour (0xRRGGBB) as kept / added / deleted using ranges."""
    r, g, b = (rgb >> 16) & 255, (rgb >> 8) & 255, rgb & 255
    # grey: channels close together, neither black nor white (0x808080, 0xA6A6A6, ...)
    if max(r, g, b) - min(r, g, b) <= 24 and 0x60 <= (r + g + b) // 3 <= 0xD0:
        return DELETED
    # red: dominant red channel
    if r >= 170 and g <= 100 and b <= 100:
        return ADDED
    return KEPT  # black, legend-blue 0070C0, form text, ...


def colour_census(doc) -> Counter:
    c: Counter = Counter()
    for p in doc:
        for b in p.get_text("dict")["blocks"]:
            for ln in b.get("lines", []):
                for s in ln["spans"]:
                    if s["text"].strip():
                        c[s["color"]] += len(s["text"])
    return c


# ---------------------------------------------------------------- stage 1: rows
def read_rows(pdf_path: Path = PDF_PATH):
    """Return pages -> rows. row = {'page','y','x','cells':[{'x','x1','segs','bold'}]}.

    Text pieces on the same baseline are merged into one row; neighbouring pieces whose gap is < 20pt are merged
    into one cell (justified prose is emitted by the PDF producer as many tiny 'lines'); wider gaps stay separate
    cells (table columns).
    """
    import pymupdf

    doc = pymupdf.open(str(pdf_path))
    pages = []
    for pno, page in enumerate(doc, start=1):
        lines = []
        for b in page.get_text("dict")["blocks"]:
            for ln in b.get("lines", []):
                segs, bold_flags = [], []
                for s in ln["spans"]:
                    t = s["text"]
                    if not t:
                        continue
                    if t.strip():
                        segs.append((classify_colour(s["color"]), t))
                        bold_flags.append(bool(s["flags"] & 16))
                    else:
                        segs.append((WS, t))
                if not bold_flags:
                    continue
                lines.append({"y": ln["bbox"][1], "x": ln["bbox"][0], "x1": ln["bbox"][2], "segs": segs,
                              "bold": all(bold_flags)})
        lines.sort(key=lambda l: (round(l["y"] / 3), l["x"]))
        rows = []
        for ln in lines:
            if rows and abs(rows[-1]["y"] - ln["y"]) < 4:
                rows[-1]["cells"].append(ln)
            else:
                rows.append({"y": ln["y"], "cells": [ln]})
        out = []
        for r in rows:
            cells = sorted(r["cells"], key=lambda l: l["x"])
            merged: list[dict] = []
            for c in cells:
                if merged and c["x"] - merged[-1]["x1"] < 20:
                    m = merged[-1]
                    m["segs"] = m["segs"] + [(WS, " ")] + c["segs"]
                    m["x1"] = max(m["x1"], c["x1"])
                    m["bold"] = m["bold"] and c["bold"]
                else:
                    merged.append(dict(c))
            out.append({"page": pno, "y": r["y"], "x": merged[0]["x"],
                        "cells": [{"x": c["x"], "x1": c["x1"], "segs": merge_segs(c["segs"]), "bold": c["bold"]}
                                  for c in merged]})
        pages.append(out)
    return pages


def merge_segs(segs):
    out = []
    for cls, t in segs:
        if out and out[-1][0] == cls:
            out[-1] = (cls, out[-1][1] + t)
        else:
            out.append((cls, t))
    return out


def norm_ws(t: str) -> str:
    return re.sub(r"\s+", " ", t.replace(" ", " ")).strip()


def raw_text(segs) -> str:
    return "".join(t for c, t in segs if c != DELETED)


def segs_current(segs) -> str:
    """Current-in-force text: deleted spans removed.  If a deleted span carried whitespace at an edge and the
    neighbours would glue together, one space is re-inserted (e.g. 'alanları~~nda ~~**ve kentsel**')."""
    out: list[str] = []
    gap = False
    for cls, t in segs:
        if cls == DELETED:
            if t[:1].isspace() or t[-1:].isspace():
                gap = True
            continue
        if gap and out and not out[-1][-1:].isspace() and not t[:1].isspace():
            out.append(" ")
        gap = False
        out.append(t)
    return norm_ws("".join(out))


def segs_deleted_text(segs) -> str:
    return norm_ws(" ".join(t for c, t in segs if c == DELETED))


def segs_redline(segs) -> str:
    """Markdown: ~~deleted~~ and **added**; kept as is."""
    out = []
    for c, t in segs:
        if c in (DELETED, ADDED):
            core = t.strip()
            if not core:
                out.append(t)
                continue
            mark = "~~" if c == DELETED else "**"
            lead = " " if t[:1].isspace() else ""
            trail = " " if t[-1:].isspace() else ""
            out.append(f"{lead}{mark}{core}{mark}{trail}")
        else:
            out.append(t)
    s = re.sub(r"\s+", " ", "".join(out)).strip()
    s = re.sub(r"\*\* \*\*", " ", s)
    s = re.sub(r"~~ ~~", " ", s)
    return s


def cell_segs(row):
    out = []
    for i, c in enumerate(row["cells"]):
        if i:
            out.append((WS, " "))
        out.extend(c["segs"])
    return merge_segs(out)


def row_bold(row) -> bool:
    return all(c["bold"] for c in row["cells"])


def counts(segs):
    k = sum(len(t.strip()) for c, t in segs if c == KEPT)
    a = sum(len(t.strip()) for c, t in segs if c == ADDED)
    d = sum(len(t.strip()) for c, t in segs if c == DELETED)
    return k, a, d


def revision_runs(segs):
    """Contiguous added/deleted runs in document order (whitespace between same-type runs is absorbed)."""
    runs: list[tuple[str, str]] = []
    cur_type, cur, pending_ws = None, [], ""
    for cls, t in segs:
        if cls == WS or (cls in (ADDED, DELETED) and not t.strip()):
            pending_ws += t
            continue
        if cls in (ADDED, DELETED):
            if cur_type == cls:
                cur.append(pending_ws + t)
            else:
                if cur_type:
                    runs.append((cur_type, norm_ws("".join(cur))))
                cur_type, cur = cls, [t]
            pending_ws = ""
        else:
            if cur_type:
                runs.append((cur_type, norm_ws("".join(cur))))
                cur_type, cur = None, []
            pending_ws = ""
    if cur_type:
        runs.append((cur_type, norm_ws("".join(cur))))
    return [{"type": ty, "text": tx} for ty, tx in runs if tx]


def strip_prefix(segs, nraw: int):
    """Drop the first `nraw` characters of raw_text(segs) (deleted segments are left untouched)."""
    out, left = [], nraw
    for cls, t in segs:
        if cls == DELETED or left <= 0:
            out.append((cls, t))
            continue
        take = min(left, len(t))
        left -= take
        rest = t[take:]
        if rest:
            out.append((cls if rest.strip() else WS, rest))
    return out


# ---------------------------------------------------------------- stage 2: structure
RE_BOLUM = re.compile(r"^[A-ZÇĞİÖŞÜ]+\s+BÖLÜM$")
RE_MADDE = re.compile(r"^(GEÇİCİ\s+)?MADDE\s+(\d+|\.\.)\s*\.?\s*[-–—]?\s*")
RE_PARA = re.compile(r"^\((\d+)\)\s*")
RE_ITEM_L = re.compile(r"^\(?([a-zçğıöşü])\)\s*")
RE_ITEM_N = re.compile(r"^(\d+)\)\s*")


class Node:
    """paragraph (level 0), item (level 1) or sub-item (level 2)"""

    def __init__(self, key, page, level):
        self.key, self.page, self.level = key, page, level
        self.segs: list = []
        self.tail_segs: list = []
        self.children: list[Node] = []
        self.tables: list = []
        self.pending_rows: list = []  # fully-deleted rows that preceded this node (they were replaced by it)
        self.table_segs: list = []  # raw coloured segments of consumed table rows (for revisions)

    def add_row(self, segs, to_tail=False):
        tgt = self.tail_segs if to_tail else self.segs
        if tgt:
            prev, nxt = segs_current(tgt), segs_current(segs)
            joiner = "" if prev.endswith("-") and nxt[:1].islower() else " "
            tgt.append((WS, joiner))
        tgt.extend(segs)

    def counts(self):
        k, a, d = counts(self.segs + self.tail_segs)
        for c in self.children:
            ck, ca, cd = c.counts()
            k, a, d = k + ck, a + ca, d + cd
        return k, a, d

    def status(self):
        k, a, d = self.counts()
        if a == 0 and d == 0:
            return "kept"
        if k == 0 and a > 0:
            return "added"
        return "amended"


def render_table(tbl) -> str:
    return "\n".join([" | ".join(tbl["header"])] + [" | ".join(r) for r in tbl["rows"]])


def load_overrides(path: Path = OVERRIDES) -> dict:
    if path.exists():
        return json.loads(path.read_text(encoding="utf-8"))
    return {}


def _flatten(pages):
    flat = []
    for pno, rows in enumerate(pages, start=1):
        if pno > BODY_LAST_PAGE:
            break
        for row in rows:
            segs = cell_segs(row)
            cur = segs_current(segs)
            if row["y"] > 780 and re.fullmatch(r"\d+", cur or ""):
                continue  # page number footer
            flat.append({"row": row, "segs": segs, "cur": cur, "page": pno, "bold": row_bold(row)})
    return flat


def build_articles(pages=None, overrides=None):
    pages = pages if pages is not None else read_rows()
    overrides = overrides if overrides is not None else load_overrides()
    warnings: list[str] = []
    articles: list[dict] = []
    tails = overrides.get("tails", [])
    table_defs = overrides.get("tables", [])
    flat = _flatten(pages)

    st = {"art": None, "section": None, "expect_section_title": False, "pending": [], "tail": False}

    def para():
        a = st["art"]
        return a["paras"][-1] if a and a["paras"] else None

    def item():
        p = para()
        return p.children[-1] if p and p.children and p.children[-1].level == 1 else None

    def new_node(parent, key, page, level, segs):
        nd = Node(key, page, level)
        nd.segs = list(segs)
        nd.pending_rows, st["pending"] = st["pending"], []
        if parent is None:
            st["art"]["paras"].append(nd)
        else:
            parent.children.append(nd)
        return nd

    def handle_text(segs, page):
        cur = segs_current(segs)
        if not cur:
            if segs_deleted_text(segs):
                st["pending"].append(segs)
            return
        raw = raw_text(segs)
        lead = len(raw) - len(raw.lstrip())
        rawl = raw.lstrip()
        m = RE_PARA.match(rawl)
        if m:
            exp = (int(para().key) + 1) if para() else 1
            if int(m.group(1)) == exp:
                st["tail"] = False
                new_node(None, m.group(1), page, 0, strip_prefix(segs, lead + m.end()))
                return
        p = para() or new_node(None, "1", page, 0, [])
        m = RE_ITEM_L.match(rawl)
        if m:
            letter = m.group(1)
            last = item().key if item() else None
            if last is None:
                exp = TR_LETTERS[0]
            else:
                i = LETTER_ORDER.get(last)
                exp = TR_LETTERS[i + 1] if i is not None and i + 1 < len(TR_LETTERS) else None
            if letter == exp:
                st["tail"] = False
                new_node(p, letter, page, 1, strip_prefix(segs, lead + m.end()))
                return
        m = RE_ITEM_N.match(rawl)
        if m:
            host = item() or p
            last = host.children[-1].key if host.children and host.children[-1].level == 2 else "0"
            if int(m.group(1)) == int(last) + 1:
                st["tail"] = False
                new_node(host, m.group(1), page, 2, strip_prefix(segs, lead + m.end()))
                return
        # continuation row
        for tl in tails:
            if tl["article"] == st["art"]["article"] and tl["paragraph"] == p.key and cur.startswith(tl["startswith"]):
                st["tail"] = True
        if st["tail"]:
            target, to_tail = p, True
        else:
            it = item()
            target = (it.children[-1] if it and it.children else None) or it or p
            to_tail = False
            if p.children and p.children[-1].level == 2 and not it:  # numeric sub-items directly under paragraph
                target = p.children[-1]
        if st["pending"]:
            target.pending_rows += st["pending"]
            st["pending"] = []
        target.add_row(segs, to_tail=to_tail)

    def start_article(m, title, page, segs):
        temp = bool(m.group(1))
        num = m.group(2)
        if temp:
            n, label = 1000 + int(num), f"GEÇİCİ MADDE {num}"
        elif num == "..":
            n, label = 58 + sum(1 for a in articles if a["unnumbered"]), "MADDE .."
        else:
            n, label = int(num), f"MADDE {num}"
        art = {"article": n, "label": label, "title": title, "page": page, "section": st["section"], "paras": [],
               "temporary": temp, "unnumbered": num == ".."}
        articles.append(art)
        st["art"], st["tail"], st["pending"] = art, False, []
        raw = raw_text(segs)
        lead = len(raw) - len(raw.lstrip())
        handle_text(strip_prefix(segs, lead + m.end()), page)

    i = 0
    table_state = None
    while i < len(flat):
        f = flat[i]
        cur, segs, page = f["cur"], f["segs"], f["page"]
        i += 1
        if table_state is not None:
            if cur:
                table_state["zone"].append(cur)
            table_state["segs"].extend(segs + [(WS, " ")])
            if cur.startswith(table_state["def"]["end"]):
                d = table_state["def"]
                tbl = {"id": d["id"], "caption": d.get("caption"), "header": d["header"], "rows": d["rows"],
                       "source": "hand-curated in regulation/overrides.json, verified against PDF row text"}
                zone = " ".join(table_state["zone"])
                for cell in [c for r in d["rows"] for c in r] + d["header"]:
                    for tok in re.findall(r"\d+(?:\.\d+)?", cell):
                        if tok not in zone:
                            warnings.append(f"table {d['id']}: token {tok!r} not found in PDF zone text")
                host = item() or para()
                host.tables.append(tbl)
                host.table_segs += table_state["segs"]
                table_state = None
            continue
        if not cur:
            if segs_deleted_text(segs) and st["art"] is not None:
                st["pending"].append(segs)
            continue
        if RE_BOLUM.match(cur):
            st["section"], st["expect_section_title"] = cur, True
            continue
        if st["expect_section_title"] and f["bold"] and not RE_MADDE.match(cur):
            st["section"] = f"{st['section']} - {cur}"
            st["expect_section_title"] = False
            continue
        m = RE_MADDE.match(raw_text(segs).lstrip()) if f["row"]["x"] < 110 else None
        if m:
            # title = bold rows immediately above (already skipped below via lookahead) -> stored in f['title']
            start_article(m, f.get("title"), page, segs)
            continue
        # bold row directly followed by a MADDE row => article title
        if f["bold"] and i < len(flat):
            nxt = flat[i]
            if nxt["row"]["x"] < 110 and RE_MADDE.match(raw_text(nxt["segs"]).lstrip()):
                nxt["title"] = cur
                continue
        if st["art"] is None:
            continue  # preamble (legend, regulation title)
        for d in table_defs:
            if d["article"] == st["art"]["article"] and cur.startswith(d["start"]):
                table_state = {"def": d, "zone": [cur], "segs": list(segs) + [(WS, " ")]}
                break
        if table_state is not None:
            if cur.startswith(table_state["def"]["end"]):  # single-row table (not used today)
                table_state = None
            continue
        handle_text(segs, page)

    # ------------------------------------------------------------------ finalise
    out = []
    for a in articles:
        art_revs: list = []
        paras = [_node_to_dict(p, art_revs) for p in a["paras"]]
        d = {"article": a["article"], "label": a["label"], "title": a["title"], "page": a["page"],
             "section": a["section"], "paragraphs": paras, "revisions": art_revs}
        if a["temporary"]:
            d["kind"] = "temporary"
        if a["unnumbered"]:
            d["unnumbered"] = True
        sts = {p["status"] for p in paras}
        d["status"] = "added" if sts == {"added"} else ("amended" if sts - {"kept"} else "kept")
        out.append(d)
    return out, warnings


def _node_to_dict(n: Node, art_revs: list) -> dict:
    head, tail = segs_current(n.segs), segs_current(n.tail_segs)
    d: dict = {"no": n.key} if n.level == 0 else {"key": n.key}
    d["text"] = head + "".join("\n" + render_table(t) for t in n.tables)
    if tail:
        d["tail"] = tail
    d["page"] = n.page
    d["status"] = n.status()
    pend = norm_ws(" ".join(segs_deleted_text(s) for s in n.pending_rows))
    revs = [{"type": "deleted", "text": pend, "whole_row": True}] if pend else []
    revs += revision_runs(n.segs + n.tail_segs)
    for r in revision_runs(n.table_segs):
        revs.append({**r, "in_table": True})
    d["revisions"] = revs
    if n.tables:
        d["tables"] = n.tables
    if n.children:
        d["items"] = [_node_to_dict(c, art_revs) for c in n.children]
    if n.level == 0:
        art_revs += [{"para": n.key, **r} for r in revs]
        for it in d.get("items", []):
            art_revs += [{"para": n.key, "item": it["key"], **r} for r in it["revisions"]]
            for sub in it.get("items", []):
                art_revs += [{"para": n.key, "item": f"{it['key']}.{sub['key']}", **r} for r in sub["revisions"]]
    d["_redline"] = {"head": segs_redline(n.segs), "tail": segs_redline(n.tail_segs),
                     "deleted_rows": [pend] if pend else []}
    return d


# ---------------------------------------------------------------- stage 3/4: outputs
def _strip_private(obj):
    if isinstance(obj, dict):
        return {k: _strip_private(v) for k, v in obj.items() if not k.startswith("_")}
    if isinstance(obj, list):
        return [_strip_private(x) for x in obj]
    return obj


def redline_markdown(arts) -> str:
    lines = ["# Kayseri BB Imar Yonetmeligi - redline view (generated by bimcheck.regulation.extract)", "",
             "Legend: `~~deleted~~` (grey in PDF, NOT in force), `**added**` (red in PDF, in force), plain = kept.", ""]

    def emit(n, depth):
        pad = "  " * depth
        r = n["_redline"]
        label = f"({n['no']})" if "no" in n else f"{n['key']})"
        for dr in r["deleted_rows"]:
            lines.append(f"{pad}- ~~{dr}~~ _(whole row deleted)_" if depth else f"~~{dr}~~ _(whole row deleted)_")
        lines.append(f"{pad}- {label} {r['head']}" if depth else f"{label} {r['head']}")
        for t in n.get("tables", []):
            lines.append("")
            lines.append(pad + "  | " + " | ".join(t["header"]) + " |")
            lines.append(pad + "  |" + "---|" * len(t["header"]))
            for row in t["rows"]:
                lines.append(pad + "  | " + " | ".join(row) + " |")
            lines.append("")
        for c in n.get("items", []):
            emit(c, depth + 1)
        if r["tail"]:
            lines.append(f"{pad}  {r['tail']}" if depth else r["tail"])
        if depth == 0:
            lines.append("")

    for a in arts:
        lines.append(f"## {a['label']} - {a['title'] or ''}  _(page {a['page']}, {a['status']})_")
        lines.append("")
        for p in a["paragraphs"]:
            emit(p, 0)
    return "\n".join(lines) + "\n"


def write_outputs(pdf_path: Path = PDF_PATH, out_json: Path = OUT_ARTICLES, out_md: Path = OUT_REDLINE):
    import pymupdf

    pages = read_rows(pdf_path)
    arts, warnings = build_articles(pages)
    out_md.write_text(redline_markdown(arts), encoding="utf-8")
    out_json.write_text(json.dumps(_strip_private(arts), ensure_ascii=False, indent=1), encoding="utf-8")
    census = colour_census(pymupdf.open(str(pdf_path)))
    report = {"articles": len(arts), "warnings": warnings,
              "colour_census": {f"#{k:06X}": v for k, v in census.most_common()},
              "classification": {"deleted": "grey (R~G~B, avg 0x60..0xD0)", "added": "red (R>=170, G,B<=100)",
                                 "kept": "everything else (black, legend-blue 0070C0)"},
              "annex_pages_skipped_from": BODY_LAST_PAGE + 1}
    (out_json.parent / "extract_report.json").write_text(json.dumps(report, ensure_ascii=False, indent=1),
                                                         encoding="utf-8")
    return arts, warnings


if __name__ == "__main__":  # pragma: no cover
    arts, warns = write_outputs()
    print(f"{len(arts)} articles written; {len(warns)} warnings")
    for w in warns:
        print("WARN", w)
