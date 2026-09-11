"""Merge per-page PDFs into one document with internal links, bookmarks and TOC.

The website's own navigation is reproduced as (a) a PDF bookmark tree, (b) a printed
table of contents with real page numbers, and (c) in-document link destinations for
every cross-page link found in the content - so clicking a topic in the PDF jumps
inside the PDF instead of opening docs.helixops.ai.
"""
from __future__ import annotations

import io
import json
import math
import os
import re
import time

from .config import BASE, pretty_url


# --------------------------------------------------------------------- helpers
def _page_ref(writer, idx):
    pg = writer.pages[idx]
    ref = getattr(pg, "indirect_reference", None)
    if ref is None:
        ref = writer._add_object(pg)
    return ref


def _latin1(s):
    return (s or "").encode("latin-1", "ignore").decode("latin-1")


def _add_link(writer, page_idx, rect, target_idx):
    from pypdf.generic import ArrayObject, DictionaryObject, FloatObject, NameObject
    from pypdf.generic import NumberObject
    annot = DictionaryObject()
    annot[NameObject("/Type")] = NameObject("/Annot")
    annot[NameObject("/Subtype")] = NameObject("/Link")
    annot[NameObject("/Rect")] = ArrayObject([FloatObject(float(v)) for v in rect])
    annot[NameObject("/Dest")] = ArrayObject([_page_ref(writer, target_idx),
                                              NameObject("/Fit")])
    annot[NameObject("/Border")] = ArrayObject([NumberObject(0), NumberObject(0),
                                                 NumberObject(0)])
    ref = writer._add_object(annot)
    page = writer.pages[page_idx]
    if "/Annots" not in page:
        page[NameObject("/Annots")] = ArrayObject()
    page[NameObject("/Annots")].append(ref)


# --------------------------------------------------------------------- cover/TOC
def _draw_cover(path, info):
    from reportlab.lib.pagesizes import A4
    from reportlab.pdfgen import canvas
    w, h = A4
    c = canvas.Canvas(path, pagesize=A4)
    c.setTitle(info["title"])
    c.setFillColorRGB(0.04, 0.39, 0.63)
    c.rect(0, h - 96, w, 96, stroke=0, fill=1)
    c.setFillColorRGB(1, 1, 1)
    c.setFont("Helvetica-Bold", 21)
    c.drawString(40, h - 52, _latin1(info["product"]))
    c.setFont("Helvetica", 13)
    c.drawString(40, h - 74, _latin1(f"Version {info['version']} - complete documentation, offline"))
    c.setFillColorRGB(0.09, 0.11, 0.14)
    y = h - 170
    c.setFont("Helvetica-Bold", 26)
    for line in _wrap(info["title"], 34):
        c.drawString(40, y, _latin1(line))
        y -= 32
    y -= 14
    c.setFont("Helvetica", 10.5)
    for label, val in info["stats"]:
        c.setFillColorRGB(0.35, 0.4, 0.45)
        c.drawString(40, y, _latin1(label))
        c.setFillColorRGB(0.09, 0.11, 0.14)
        c.setFont("Helvetica-Bold", 11.5)
        c.drawString(230, y, _latin1(val))
        c.setFont("Helvetica", 10.5)
        y -= 19
    y -= 16
    c.setFillColorRGB(0.35, 0.4, 0.45)
    c.drawString(40, y, "Contents of this file")
    y -= 17
    c.setFillColorRGB(0.09, 0.11, 0.14)
    for line in info["notes"]:
        for ln in _wrap(line, 92):
            c.drawString(40, y, _latin1(ln))
            y -= 13.5
        y -= 3
    c.setFont("Helvetica-Oblique", 8.5)
    c.setFillColorRGB(0.42, 0.46, 0.5)
    c.drawString(40, 54, _latin1(f"Built {info['built']} - source: {info['source_url']}"))
    c.showPage()
    c.save()


def _wrap(s, n):
    words, lines, cur = (s or "").split(), [], ""
    for word in words:
        if len(cur) + len(word) + 1 > n:
            lines.append(cur)
            cur = word
        else:
            cur = f"{cur} {word}".strip()
    if cur:
        lines.append(cur)
    return lines or [""]


def _draw_toc(path, entries, page_size=(595.27559, 841.88976), font_size=8.6,
              leading=11.4, top=64, bottom=44, indent=11):
    """Draw a dot-leader TOC. Returns [{row rect, doc, page}] for linking."""
    from reportlab.pdfgen import canvas
    w, h = page_size
    c = canvas.Canvas(path, pagesize=page_size)
    rows_per_page = max(8, int((h - top - bottom) // leading))
    pages, rows, cur = [], [], []
    for e in entries:
        cur.append(e)
        if len(cur) == rows_per_page:
            pages.append(cur)
            cur = []
    if cur:
        pages.append(cur)
    for pi, chunk in enumerate(pages):
        if pi:
            c.setFont("Helvetica-Bold", 13)
            c.setFillColorRGB(0.04, 0.39, 0.63)
            c.drawString(40, h - 42, "Table of contents (continued)")
        else:
            c.setFont("Helvetica-Bold", 15)
            c.setFillColorRGB(0.04, 0.39, 0.63)
            c.drawString(40, h - 42, "Table of contents")
            c.setFillColorRGB(0.4, 0.45, 0.5)
            c.setFont("Helvetica", 7.8)
            c.drawString(40, h - 53, "Every page of the documentation set, in navigation order, "
                                      "with its printed page number and PDF page number")
        y = h - top
        c.setFont("Helvetica", font_size)
        for e in chunk:
            lvl = min(6, max(1, int(e.get("depth", 1))))
            x = 40 + (lvl - 1) * indent
            bold = lvl <= 2
            title = e["title"]
            maxw = w - x - 96
            c.setFont("Helvetica-Bold" if bold else "Helvetica",
                      font_size + (0.9 if lvl == 1 else 0))
            while c.stringWidth(title, "Helvetica-Bold" if bold else "Helvetica",
                                font_size + (0.9 if lvl == 1 else 0)) > maxw:
                title = title[:-3]
            title = title.rstrip() + ("..." if title != e["title"] else "")
            c.setFillColorRGB(0.06, 0.08, 0.12)
            c.drawString(x, y, _latin1(title))
            tnum = str(e["page"])
            c.setFont("Helvetica", font_size - 0.6)
            c.setFillColorRGB(0.25, 0.3, 0.36)
            tw = c.stringWidth(tnum, "Helvetica", font_size - 0.6)
            c.drawString(w - 40 - tw, y, _latin1(tnum))
            c.setFillColorRGB(0.72, 0.76, 0.8)
            tx = x + c.stringWidth(title, "Helvetica-Bold" if bold else "Helvetica",
                                   font_size + (0.9 if lvl == 1 else 0)) + 3
            dots = int((w - 46 - tw - 4 - tx) / 3.1)
            if dots > 1:
                c.setFont("Helvetica", 6.5)
                c.drawString(tx, y + 0.6, "." * dots)
            rows.append({"page_index_in_toc": pi, "rect": [x, y - 3, w - 40, y + font_size + 2],
                         "doc": e["doc"], "target": e["pdf_page"] - 1})
            y -= leading
        c.showPage()
    c.save()
    return len(pages), rows


# ---------------------------------------------------------------------- stamps
def _draw_stamps(path, rows, page_size=(595.27559, 841.88976)):
    """One blank page per content page, with footer text (global page numbers)."""
    from reportlab.pdfgen import canvas
    w, h = page_size
    c = canvas.Canvas(path, pagesize=page_size)
    c.setFillColorRGB(0, 0, 0)
    for r in rows:
        c.setFont("Helvetica", 7.2)
        c.setFillColorRGB(0.45, 0.5, 0.55)
        left = _latin1((r.get("section") or "")[:64])
        c.drawString(40, 26, left)
        c.drawRightString(w - 40, 26, _latin1(r.get("product") or ""))
        c.setFont("Helvetica-Bold", 7.8)
        c.setFillColorRGB(0.2, 0.24, 0.3)
        label = f"page {r['page']} of {r['total']}"
        c.drawCentredString(w / 2.0, 26, label)
        if r.get("title"):
            c.setFont("Helvetica", 6.6)
            c.setFillColorRGB(0.55, 0.58, 0.62)
            c.drawCentredString(w / 2.0, 17, _latin1(r["title"][:110]))
        c.showPage()
    c.save()


# ------------------------------------------------------------------ the builder
def build_link_resolver(inv, metas, space_path):
    """map any URL form we may find inside the PDF -> canonical doc id."""
    sd = space_path.replace("/", ".")
    m = {}
    for doc in inv.nodes:
        pretty = pretty_url(doc, space_path, sd)
        for u in {pretty, pretty.rstrip("/"), pretty.replace("/bin/", "/bin/view/"),
                  pretty.replace(BASE, "https://docs.bmc.com/xwiki"),
                  pretty.replace(BASE, "http://docs.helixops.ai"),
                  pretty.replace(BASE, "https://docs.helixops.ai/xwiki/bin/view")}:
            m[re.sub(r"/$", "", u)] = doc
    return m


def assemble(inv, metas, render_index, out_dir, product, version, opts, verbose=True):
    """Produce the merged PDF. Returns a summary dict."""
    from pypdf import PdfReader, PdfWriter
    from pypdf.generic import ArrayObject, NameObject

    t0 = time.time()
    os.makedirs(out_dir, exist_ok=True)
    resolver = build_link_resolver(inv, metas, opts.space_path)

    order = [d for d in inv.walk()]
    content = []
    for d in order:
        r = render_index.get(d) or metas.get(d, {}).get("_render") or {}
        if metas.get(d, {}).get("is_redirect"):
            continue
        if r.get("ok") and r.get("pages", 0) > 0:
            content.append((d, r))
    if opts.max_pages and len(content) > opts.max_pages:
        content = content[:opts.max_pages]
    if not content:
        raise RuntimeError("nothing to merge - no page rendered successfully")

    # ---- page ranges, then TOC layout (iterate until the TOC length is stable)
    total_content = sum(r["pages"] for _d, r in content)
    entries_meta, start = [], {}
    p = 0
    for d, r in content:
        start[d] = p
        entries_meta.append({"doc": d, "title": metas[d]["title"],
                             "depth": inv.nodes[d]["depth"], "pages": r["pages"]})
        p += r["pages"]

    top_section = {}
    for d, r in content:  # nearest ancestor that is a top-level nav section
        node = inv.nodes[d]
        chain = []
        while node:
            chain.append(node)
            node = inv.nodes.get(node["parent"]) if node.get("parent") else None
        top_section[d] = chain[-1]["title"] if chain else ""

    def layout(toc_pages):
        offset = 1 + toc_pages
        return offset, [dict(e, page=start[e["doc"]] + offset + 1,
                             pdf_page=start[e["doc"]] + offset + 1) for e in entries_meta]

    toc_pages = max(1, math.ceil(len(entries_meta) * 11.4 / (841.89 - 108)))
    offset, entries = layout(toc_pages)
    for _ in range(4):
        new_toc = max(1, math.ceil(len(entries) * 11.4 / (841.89 - 108)))
        if new_toc == toc_pages:
            break
        toc_pages = new_toc
        offset, entries = layout(toc_pages)

    info = {
        "title": f"{product} {version} - complete documentation",
        "product": product, "version": version,
        "built": time.strftime("%Y-%m-%d %H:%M UTC", time.gmtime()),
        "source_url": f"{BASE}/bin/{opts.space_path}/",
        "stats": [
            ("documentation pages included", f"{len(content):,}"),
            ("PDF pages", f"{total_content + offset:,}"),
            ("images rendered", f"{sum(metas[d].get('images', 0) for d, _ in content):,}"),
            ("tables rendered", f"{sum(metas[d].get('tables', 0) for d, _ in content):,}"),
            ("content words", f"{sum(metas[d].get('words', 0) for d, _ in content):,}"),
            ("navigation bookmarks", f"{len(content):,}"),
            ("links that stay inside the PDF", "all"),
            ("external web links kept", f"{sum(metas[d].get('links_external', 0) for d, _ in content):,}"),
        ],
        "notes": [
            "This file contains the whole documentation space, page by page, in the same order "
            "as the website navigation menu. Nothing is truncated.",
            "Every link to a page of this documentation set (including the navigation menu items) "
            "was rewritten to an in-document jump: clicking it moves you to that page in this file "
            "instead of opening docs.helixops.ai.",
            "Use the bookmarks/outline panel for the menu tree, the table of contents below for "
            "printed page numbers, and full-text search to find any line of the documentation.",
            "Each page keeps a footer with its printed page number and a source line naming the "
            "original page, so any page can be traced back to its URL.",
        ],
    }
    _draw_cover(os.path.join(out_dir, "cover.pdf"), info)
    toc_pdf = os.path.join(out_dir, "toc.pdf")
    n_toc, toc_rows = _draw_toc(toc_pdf, entries)
    if n_toc != toc_pages:  # layout disagreed with the estimate -> rebuild once
        toc_pages = n_toc
        offset, entries = layout(toc_pages)
        n_toc, toc_rows = _draw_toc(toc_pdf, entries)
        assert n_toc == toc_pages, "TOC layout did not converge"

    # ---- merge
    writer = PdfWriter()
    writer.append(os.path.join(out_dir, "cover.pdf"), import_outline=False)
    writer.append(toc_pdf, import_outline=False)
    structure = {}
    for d, r in content:
        before = len(writer.pages)
        writer.append(r["pdf"], import_outline=False)
        structure[d] = {"first_page": before + 1, "last_page": len(writer.pages),
                        "pages": len(writer.pages) - before}
    n_pages = len(writer.pages)

    # ---- stamps (global page numbers + section) on content pages
    if not opts.no_stamp:
        rows = []
        k = 0
        for d, r in content:
            s = structure[d]
            for i in range(s["first_page"], s["last_page"] + 1):
                rows.append({"page": i, "total": n_pages,
                              "section": top_section.get(d, ""),
                              "title": metas[d]["title"] if i == s["first_page"] else "",
                              "product": f"{product} {version}"})
                k += 1
        _draw_stamps(os.path.join(out_dir, "stamps.pdf"), rows)
        sr = PdfReader(os.path.join(out_dir, "stamps.pdf"))
        for idx in range(len(rows)):
            writer.pages[offset + idx].merge_page(sr.pages[idx])
        sr.close()
        if verbose:
            print(f"[assemble] stamped {len(rows)} content pages", flush=True)

    # ---- rewrite documentation links into in-document jumps
    internalized = 0
    left_external = 0
    unresolved = []
    doc_by_url = resolver
    redirect_alias = {d: metas[d]["redirect_to"] for d in metas
                      if metas.get(d) and metas[d].get("is_redirect") and metas[d].get("redirect_to")}
    for pi in range(offset, n_pages):
        page = writer.pages[pi]
        annots = page.get("/Annots")
        if not annots:
            continue
        for a in list(annots):
            try:
                o = a.get_object()
            except Exception:
                continue
            act = o.get("/A")
            if act is None:
                continue
            act = act.get_object()
            uri = act.get("/URI")
            if uri is None:
                continue
            u = re.sub(r"/$", "", str(uri).split("#")[0].replace("\\", "").strip())
            doc = doc_by_url.get(u)
            if doc is None:
                doc = doc_by_url.get(u.replace("https://docs.helixops.ai", BASE))
            if doc is not None:
                # a link to a moved/renamed page must land on its new content
                for _ in range(6):
                    nxt = redirect_alias.get(doc)
                    if not nxt or nxt not in start:
                        break
                    doc = nxt
                tgt = start.get(doc)
                if tgt is None:
                    unresolved.append(str(uri))
                    left_external += 1
                    continue
                o[NameObject("/Dest")] = ArrayObject([_page_ref(writer, tgt + offset),
                                                       NameObject("/Fit")])
                del o[NameObject("/A")]
                internalized += 1
            else:
                left_external += 1

    # ---- make the TOC rows clickable
    for r in toc_rows:
        tgt = r["target"]
        if 0 <= tgt < n_pages:
            _add_link(writer, r["page_index_in_toc"], r["rect"], tgt)

    # ---- bookmarks = the website's menu tree
    outline = {}
    for d, r in content:
        node = inv.nodes[d]
        title = _latin1(metas[d]["title"])[:180] or d
        parent_ref = None
        par = node.get("parent")
        while par:
            if par in outline and par in structure:
                parent_ref = outline[par]
                break
            par = inv.nodes.get(par, {}).get("parent") if inv.nodes.get(par) else None
        try:
            ref = writer.add_outline_item(title, structure[d]["first_page"] - 1,
                                          parent=parent_ref,
                                          bold=node["depth"] <= 1,
                                          color=(0, 0.25, 0.5) if node["depth"] <= 1 else None)
        except TypeError:
            ref = writer.add_outline_item(title, structure[d]["first_page"] - 1,
                                          parent=parent_ref)
        outline[d] = ref

    writer.add_metadata({
        "/Title": f"{product} {version} - complete documentation",
        "/Author": product, "/Creator": "helix-offline-pdf",
        "/Producer": "helix-offline-pdf (WeasyPrint + pypdf)",
        "/Subject": info["source_url"],
        "/Keywords": ",".join([product, version, "offline", "complete"]),
        "/CreationDate": "D:%s" % time.strftime("%Y%m%d%H%M%SZ", time.gmtime()),
    })
    try:
        writer._root_object[NameObject("/PageMode")] = NameObject("/UseOutlines")
        vp = DictionaryObjectVP()
        writer._root_object[NameObject("/ViewerPreferences")] = vp
    except Exception:
        pass
    out_pdf = opts.out or os.path.join(out_dir, f"{product.replace(' ', '-')}-{version}-complete.pdf")
    with open(out_pdf, "wb") as fh:
        writer.write(fh)

    json.dump({"space_path": opts.space_path, "offset": offset, "toc_pages": toc_pages,
               "cover_pages": 1, "n_pages": n_pages, "docs": len(content),
               "structure": structure, "internalized_links": internalized,
               "external_links_left": left_external,
               "unresolved_links": sorted(set(unresolved))[:400]},
              open(os.path.join(out_dir, "structure.json"), "w"), indent=1)
    if verbose:
        print(f"[assemble] pages={n_pages} docs={len(content)} internalized={internalized} "
              f"external_left={left_external} out={out_pdf} t={time.time()-t0:.0f}s",
              flush=True)
    return {"out_pdf": out_pdf, "pages": n_pages, "docs": len(content),
            "internalized": internalized, "external": left_external,
            "toc_pages": toc_pages, "offset": offset, "structure": structure,
            "unresolved": len(set(unresolved)), "seconds": round(time.time() - t0, 1)}


def DictionaryObjectVP():
    from pypdf.generic import BooleanObject, DictionaryObject, NameObject
    d = DictionaryObject()
    d[NameObject("/FitWindow")] = BooleanObject(True)
    d[NameObject("/HideMenubar")] = BooleanObject(False)
    d[NameObject("/CenterWindow")] = BooleanObject(False)
    return d
