"""Recovery paths for pages a CSS engine cannot lay out.

One page once killed a whole build: a documentation page whose layout made
WeasyPrint spin (240 s alarm, then an unbounded serial retry that ran for over an
hour and took the run down with it, PDF and all). Losing a page is not acceptable
here - the set has to be complete and every in-space link has to land on real
content - so instead of failing, the page walks down a ladder:

  1. render it again, serially, with a bound         (a slow page finishes)
  2. render a *CSS-flattened* copy                   (most layout blow-ups are
     caused by selectors/nested-table CSS, and the browser defaults that remain
     still give us real tables and embedded images)
  3. lay the page out with reportlab, no CSS at all  (linear, cannot hang)

Every rung that succeeds produces a normal per-page PDF, so the merge, bookmarks,
TOC and in-document link rewriting are unchanged; the page is just recorded as
`degraded` so the report says exactly what was traded away (styling, never text).

`profile_html` exists because step 2/3 are diagnostics too: the numbers it returns
are what tells us *why* an engine choked on a page.
"""
from __future__ import annotations

import os
import re
from xml.sax.saxutils import escape

from .config import BASE, pretty_url


# --------------------------------------------------------------- diagnostics
def profile_html(html_file: str) -> dict:
    """Structure of one cleaned page - the 'why did layout explode' fingerprint."""
    from bs4 import BeautifulSoup

    raw = open(html_file, encoding="utf-8", errors="replace").read()
    soup = BeautifulSoup(raw, "lxml" if _has_lxml() else "html.parser")
    tables = soup.find_all("table")

    def _cells(t):
        return len(t.find_all(["td", "th"]))

    nested = sum(1 for t in tables if t.find_parent("table") is not None)
    data_uri = [len(m) for m in re.findall(r"data:[^\"')\s]+", raw)]
    imgs = soup.find_all("img")
    return {
        "bytes": len(raw),
        "elements": len(soup.find_all(True)),
        "tables": len(tables),
        "tables_nested": nested,
        "max_table_cells": max([_cells(t) for t in tables], default=0),
        "max_table_rows": max([len(t.find_all("tr")) for t in tables], default=0),
        "pre_bytes": sum(len(p.get_text()) for p in soup.find_all("pre")),
        "style_bytes": sum(len(s.get_text() or "") for s in soup.find_all("style")),
        "inline_style_attrs": raw.count("style="),
        "imgs": len(imgs),
        "data_uri_items": len(data_uri),
        "data_uri_bytes": sum(data_uri),
        "links": len(soup.find_all("a")),
    }


def _has_lxml() -> bool:
    try:
        import lxml                      # noqa: F401
        return True
    except Exception:
        return False


def _soup(html_file):
    from bs4 import BeautifulSoup
    raw = open(html_file, encoding="utf-8", errors="replace").read()
    return BeautifulSoup(raw, "lxml" if _has_lxml() else "html.parser")


# --------------------------------------------------------- rung 2: flatten CSS
def flatten_css(html_file: str, out_file: str) -> dict:
    """Same content, no author CSS: strip <style> blocks and style= attributes.

    Keeps <table>/<img>/<a> so the result is still a structured page with embedded
    images and working links - it just uses the renderer's default layout, which is
    where pathological selector/table CSS stops being able to blow up.
    """
    soup = _soup(html_file)
    removed = {"style_blocks": 0, "style_attrs": 0, "class_attrs": 0}
    for s in soup.find_all("style"):
        s.decompose()
        removed["style_blocks"] += 1
    for t in soup.find_all(True):
        if t.has_attr("style"):
            del t["style"]
            removed["style_attrs"] += 1
        if t.has_attr("class"):          # a stylesheet we removed could size these
            del t["class"]
            removed["class_attrs"] += 1
    head = soup.find("head")
    if head is None and soup.html is not None:
        head = soup.new_tag("head")
        soup.html.insert(0, head)
    if head is not None:
        meta = soup.new_tag("style")
        meta.append("body{font-family:DejaVu Sans,Helvetica,sans-serif;font-size:9.5pt;"
                    "line-height:1.35}table{border-collapse:collapse;width:100%}"
                    "td,th{border:1px solid #b8c0c8;padding:3px;font-size:8.5pt;"
                    "vertical-align:top}img{max-width:100%}")
        head.append(meta)
    open(out_file, "w", encoding="utf-8").write(str(soup))
    return removed


# ---------------------------------------------------- rung 3: reportlab layout
def _markup(node) -> str:
    """A bs4 node -> reportlab paragraph markup (links survive as real anchors)."""
    from bs4.element import NavigableString

    if isinstance(node, NavigableString):
        return escape(re.sub(r"\s+", " ", str(node)))
    name = getattr(node, "name", None)
    if name is None:
        return ""
    if name in ("script", "noscript", "style"):
        return ""
    if name == "img":
        src = str(node.get("src") or "")
        if src.startswith("file:") or src.startswith("/"):
            src = src.split("?")[0]
        return f" [image: {escape(os.path.basename(src) or 'image')}] "
    if name == "br":
        return "<br/>"
    inner = "".join(_markup(c) for c in node.children)
    if name == "a" and node.get("href"):
        href = escape(str(node["href"]), {'"': "&quot;"})
        return f'<link href="{href}" color="#0b58d9">{inner or href}</link>'
    if name in ("b", "strong"):
        return f"<b>{inner}</b>"
    if name in ("i", "em"):
        return f"<i>{inner}</i>"
    if name in ("code", "tt", "kbd", "samp"):
        return f'<font face="Courier">{inner}</font>'
    return inner


def render_text_pdf(html_file: str, pdf_file: str, title: str, source_url: str,
                    page_size: str = "A4", note: str = "") -> int:
    """Lay the page out as text + tables with reportlab. Returns its PDF page count."""
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4, letter
    from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
    from reportlab.lib.units import mm
    from reportlab.platypus import (KeepTogether, Paragraph, SimpleDocTemplate, Spacer,
                                    Table, TableStyle)

    soup = _soup(html_file)
    ss = getSampleStyleSheet()
    st = {
        "h1": ParagraphStyle("h1x", parent=ss["Heading1"], fontSize=17, leading=21,
                             spaceAfter=6, textColor=colors.HexColor("#123a63")),
        "h2": ParagraphStyle("h2x", parent=ss["Heading2"], fontSize=13, leading=17,
                             spaceBefore=8, spaceAfter=4,
                             textColor=colors.HexColor("#123a63")),
        "h3": ParagraphStyle("h3x", parent=ss["Heading3"], fontSize=11.5, leading=15,
                             spaceBefore=6, spaceAfter=3),
        "p": ParagraphStyle("px", parent=ss["BodyText"], fontSize=9.5, leading=12.6,
                            spaceAfter=4),
        "li": ParagraphStyle("lix", parent=ss["BodyText"], fontSize=9.5,
                             leading=12.6, leftIndent=9, spaceAfter=2),
        "pre": ParagraphStyle("prex", parent=ss["Code"], fontSize=8, leading=10,
                              backColor=colors.HexColor("#f4f6f8"), spaceAfter=5),
        "cell": ParagraphStyle("cellx", parent=ss["BodyText"], fontSize=7.6,
                               leading=9.6),
        "small": ParagraphStyle("sml", parent=ss["BodyText"], fontSize=7.2,
                                leading=9, textColor=colors.HexColor("#7a828c")),
    }

    root = soup.find(id="content") or soup.find("main") or soup.body or soup
    story = []
    if title:
        story.append(Paragraph(_markup(title) or "", st["h1"]))
    banner = ("This page could not be laid out by the PDF's CSS engine (it exceeded the "
              "render limit). Its full text, tables and links are reproduced below with "
              "the fallback layout engine; images are listed, not drawn.")
    if note:
        banner += " " + note
    story.append(KeepTogether([
        Spacer(1, 2),
        Table([[Paragraph(banner, st["small"])]], colWidths=[178 * mm],
              style=TableStyle([("BOX", (0, 0), (-1, -1), 0.6,
                                 colors.HexColor("#c98f00")),
                                ("BACKGROUND", (0, 0), (-1, -1),
                                 colors.HexColor("#fff8e6")),
                                ("LEFTPADDING", (0, 0), (-1, -1), 6),
                                ("TOPPADDING", (0, 0), (-1, -1), 4),
                                ("BOTTOMPADDING", (0, 0), (-1, -1), 4)])),
        Spacer(1, 8)]))

    tbl_grid = TableStyle([("GRID", (0, 0), (-1, -1), 0.25, colors.HexColor("#b8c0c8")),
                           ("VALIGN", (0, 0), (-1, -1), "TOP"),
                           ("LEFTPADDING", (0, 0), (-1, -1), 3),
                           ("RIGHTPADDING", (0, 0), (-1, -1), 3),
                           ("TOPPADDING", (0, 0), (-1, -1), 2),
                           ("BOTTOMPADDING", (0, 0), (-1, -1), 2)])

    for el in root.find_all(["h1", "h2", "h3", "h4", "p", "li", "pre", "table",
                             "div"]):
        if el.find_parent(["table", "pre", "li"]) is not None:
            continue
        if el.find(True) is not None and el.name == "div" \
                and not el.get("class") == ["hx-src"] and el.find("img") is None:
            continue                                   # containers are walked by children
        name = el.name
        if name in ("h1", "h2", "h3"):
            story.append(Paragraph(_markup(el), st[name]))
        elif name == "h4":
            story.append(Paragraph(f"<b>{_markup(el)}</b>", st["p"]))
        elif name == "pre":
            txt = escape(el.get_text("\n"))
            story.append(Paragraph(re.sub(r"\n{3,}", "\n\n", txt).replace("\n", "<br/>"),
                                   st["pre"]))
        elif name == "table":
            rows = []
            for tr in el.find_all("tr"):
                if tr.find_parent("table") is not el:
                    continue
                cells = [Paragraph(_markup(td) or "&nbsp;", st["cell"])
                         for td in tr.find_all(["td", "th"], recursive=False)]
                if cells:
                    rows.append(cells)
            if rows:
                ncol = max(len(r) for r in rows)
                for r in rows:
                    while len(r) < ncol:
                        r.append(Paragraph("", st["cell"]))
                w = 178.0 / max(1, ncol)
                story.append(Table(rows, colWidths=[w * mm] * ncol, style=tbl_grid,
                                   repeatRows=1))
                story.append(Spacer(1, 6))
        else:
            txt = _markup(el).strip()
            if txt:
                story.append(Paragraph(txt, st["li"] if name == "li" else st["p"]))
    imgs = [str(i.get("src") or "") for i in root.find_all("img")]
    if imgs:
        story.append(Paragraph("<i>Images on this page:</i> " +
                               escape(", ".join(os.path.basename(u.split("?")[0])
                                                for u in imgs if u))[:1800], st["small"]))
    story.append(Paragraph(f"BMC Helix documentation &middot; "
                           f'<link href="{escape(source_url, {chr(34): chr(34)})}">'
                           f"{escape(source_url)}</link>", st["small"]))

    size = {"Letter": letter, "A4": A4}.get(page_size, A4)
    doc = SimpleDocTemplate(pdf_file, pagesize=size, title=title or "page",
                            author="BMC Helix documentation (offline build)",
                            leftMargin=16 * mm, rightMargin=16 * mm,
                            topMargin=14 * mm, bottomMargin=14 * mm)
    doc.build(story)
    from pypdf import PdfReader
    return len(PdfReader(pdf_file).pages)


def page_source_url(doc: str, space_path: str, meta: dict | None = None) -> str:
    """The portal URL of a document id, for the marker/link in the fallback page."""
    if meta and meta.get("url"):
        return meta["url"]
    return pretty_url(doc, space_path, space_path.replace("/", "."))
