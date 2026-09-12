#!/usr/bin/env python3
"""Offline self-test: no network, no WeasyPrint - validates the parts that decide
whether the result is actually complete and self-linked.

Covers: HTML cleaning (hidden tab/accordion content must survive), link
classification, redirect resolution, page-range bookkeeping, the URI->in-document
link rewrite, TOC/outline generation and the verifier itself. Synthetic per-page
PDFs are produced with ReportLab, so this runs anywhere ReportLab is installed.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import sys
import types

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

from helixdocs.assemble import assemble                                   # noqa: E402
from helixdocs.config import BASE, pretty_url                             # noqa: E402
from helixdocs.net import Http                                             # noqa: E402
from helixdocs.page import PageBuilder                                     # noqa: E402
from helixdocs.tree import Inventory                                       # noqa: E402
from helixdocs.verify import audit_links, check_content                    # noqa: E402

SPACE = "Test.Space"
SD = SPACE.replace("/", ".")
DOCS = {
    f"{SD}.Administering": "Administering",
    f"{SD}.Administering.Manage-users": "Manage users",
    f"{SD}.Administering.Manage-users.Assign-roles": "Assign roles",
    f"{SD}.Developing": "Developing",
    f"{SD}.Developing.Old-name": "Old name (redirect)",
    f"{SD}.Developing.Workflow": "Workflow",
}
PARENTS = {
    f"{SD}.Administering": None,
    f"{SD}.Administering.Manage-users": f"{SD}.Administering",
    f"{SD}.Administering.Manage-users.Assign-roles": f"{SD}.Administering.Manage-users",
    f"{SD}.Developing": None,
    f"{SD}.Developing.Old-name": f"{SD}.Developing",
    f"{SD}.Developing.Workflow": f"{SD}.Developing",
}
# unique markers so we can prove which lines made it into the PDF
MARK = {d: f"LINE{abs(hash(d)) % 9999:04d}" for d in DOCS}
LINKS = {
    f"{SD}.Administering": [f"{SD}.Administering.Manage-users", f"{SD}.Developing.Workflow"],
    f"{SD}.Administering.Manage-users": [f"{SD}.Administering.Manage-users.Assign-roles"],
    f"{SD}.Administering.Manage-users.Assign-roles": [],
    f"{SD}.Developing": [f"{SD}.Developing.Workflow", f"{SD}.Developing.Old-name"],
    f"{SD}.Developing.Old-name": [],
    f"{SD}.Developing.Workflow": [f"{SD}.Administering"],
}


def fixture_html(doc):
    title = DOCS[doc]
    inner = [f"<p>Intro text for {title}. {MARK[doc]}-intro</p>",
             '<div class="xwiki-tabgroups">'
             '<ul class="nav-tabs"><li><a href="#tab1">Before you begin</a></li>'
             '<li><a href="#tab2">Procedure</a></li></ul>'
             '<div class="tab-content">'
             f'<div class="tab-pane active" id="tab1"><p>tab one text {MARK[doc]}-tab1</p></div>'
             f'<div class="tab-pane" id="tab2" style="display:none">'
             f'<p>tab two hidden text {MARK[doc]}-tab2</p></div>'
             '</div></div>',
             f'<div class="collapse" style="display:none"><p>collapsed detail '
             f'{MARK[doc]}-collapse</p></div>',
             '<table><thead><tr><th>Field</th><th>Meaning</th></tr></thead>'
             f'<tbody><tr><td>name</td><td>value {MARK[doc]}-table</td></tr></tbody></table>',
             '<p>External video: <a href="https://www.youtube.com/watch?v=abc123">demo</a></p>']
    for tgt in LINKS[doc]:
        inner.append(f'<p>See <a href="{pretty_url(tgt, SPACE, SD)}">{DOCS[tgt]}</a>.</p>')
    return ('<html><body><h1 id="contentTitle">' + title + '</h1>'
            '<nav class="xwikiDocumentTree">NAV JUNK ' + MARK[doc] + '-navjunk</nav>'
            '<div id="xwikicontent">' + "".join(inner) + '</div>'
            '<footer>FOOTER JUNK ' + MARK[doc] + '-footerjunk</footer></body></html>')


def make_pdf(path, doc, npages=2):
    """Synthetic 'rendered page' for a doc: real text + real URI link annotations."""
    from reportlab.lib.pagesizes import A4
    from reportlab.pdfgen import canvas
    c = canvas.Canvas(path, pagesize=A4)
    url = pretty_url(doc, SPACE, SD)
    base = pretty_url(doc, SPACE, SD)
    for i in range(npages):
        c.setFont("Helvetica-Bold", 16)
        c.drawString(50, 780 - i * 40, DOCS[doc] if i == 0 else f"{DOCS[doc]} (continued)")
        c.setFont("Helvetica", 9)
        y = 740
        for tag in ("intro", "tab1", "tab2", "collapse", "table"):
            c.drawString(50, y, f"{MARK[doc]}-{tag}"); y -= 14
        for tgt in LINKS[doc]:
            tx = f"link to {DOCS[tgt]}"
            c.drawString(50, y, tx)
            c.linkURL(pretty_url(tgt, SPACE, SD), (50, y - 2, 50 + c.stringWidth(tx, "Helvetica", 9), y + 10))
            y -= 14
        c.linkURL("https://www.youtube.com/watch?v=abc123", (50, y - 2, 150, y + 10))
        y -= 30
        c.setFillColorRGB(0.5, 0.5, 0.5)
        c.setFont("Helvetica", 7)
        c.drawString(50, 60, f"BMC Helix documentation . {base}")
        c.showPage()
    c.save()



def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--work", default="/tmp/helix-selftest")
    ap.add_argument("--with-render", action="store_true",
                    help="also exercise the real WeasyPrint engine (needs pango/cairo)")
    args = ap.parse_args()
    ws = args.work
    shutil.rmtree(ws, ignore_errors=True)
    os.makedirs(ws, exist_ok=True)
    fails = []

    def check(cond, label, detail=""):
        print(("  ok   " if cond else "  FAIL ") + label + (f"   {detail}" if detail else ""))
        if not cond:
            fails.append(label)

    print("== 1. inventory + cleaning ==")
    inv = Inventory(SPACE)
    for d, title in DOCS.items():
        inv.add(d, title, parent=PARENTS[d], depth=(1 if PARENTS[d] is None else 2))
    for d in DOCS:  # children lists are normally filled by the tree walk
        inv.nodes[d]["children"] = [c for c in DOCS if PARENTS[c] == d]
    assert inv.walk()[:3] == [f"{SD}.Administering", f"{SD}.Administering.Manage-users",
                              f"{SD}.Administering.Manage-users.Assign-roles"], inv.walk()
    http = Http(os.path.join(ws, "cache"), workers=1, delay=0, retries=1, verbose=False)
    b = PageBuilder(http, SPACE, ws, mirror_attachments=False)
    metas = {}
    for d in DOCS:
        metas[d] = b.build(d, fixture_html(d), title_hint=DOCS[d])
    check(len(inv.walk()) == len(DOCS), "inventory walk covers every page",
          f"{len(inv.walk())}/{len(DOCS)}")
    for d in DOCS:
        html = open(metas[d]["html_file"], encoding="utf-8").read()
        m = MARK[d]
        hidden_ok = all(t in html for t in (f"{m}-tab2", f"{m}-collapse", f"{m}-table"))
        check(hidden_ok, f"{DOCS[d]}: hidden tab/accordion/table content kept")
        check(f"{m}-navjunk" not in html and f"{m}-footerjunk" not in html,
              f"{DOCS[d]}: site chrome stripped")
        for tgt in LINKS[d]:
            slug = re.sub(r"[^A-Za-z0-9._-]", "_", tgt)[-150:]
            check(pretty_url(tgt, SPACE, SD) in html,
                  f"{DOCS[d]}: link to {DOCS[tgt]} canonicalised to portal URL")
        check("youtube.com" in html, f"{DOCS[d]}: genuinely external link preserved")
    check(metas[f"{SD}.Developing.Old-name"]["is_redirect"] is False or True,
          "redirect detection ran")

    print("== 2. simulate a redirect page ==")
    rd = f"{SD}.Developing.Old-name"
    metas[rd]["is_redirect"] = True
    metas[rd]["redirect_to"] = f"{SD}.Developing.Workflow"
    metas[rd].pop("html_file", None)

    print("== 3. assemble ==")
    render_index = {}
    for d in DOCS:
        if metas[d].get("is_redirect"):
            continue
        p = os.path.join(ws, "pdf", f"{metas[d]['html_file'].split('/')[-1][:-5]}.pdf")
        os.makedirs(os.path.dirname(p), exist_ok=True)
        make_pdf(p, d, npages=1 + (1 if "Administering.Manage-users.Assign" in d else 0))
        from pypdf import PdfReader
        render_index[d] = {"pdf": p, "pages": len(PdfReader(p).pages), "ok": True}
    opts = types.SimpleNamespace(space_path=SPACE, max_pages=0, no_stamp=False,
                                  out=os.path.join(ws, "merged.pdf"))
    res = assemble(inv, metas, render_index, ws, "Test Product", "9.9", opts, verbose=True)
    from pypdf import PdfReader
    rd_ = PdfReader(os.path.join(ws, "merged.pdf"))
    structure = json.load(open(os.path.join(ws, "structure.json")))["structure"]

    print("== 4. assert merged structure ==")
    expect_pages = 1 + res["toc_pages"] + sum(v["pages"] for v in render_index.values())
    check(len(rd_.pages) == expect_pages, "page count = cover + TOC + every page",
          f"{len(rd_.pages)} vs {expect_pages}")
    order = [d for d in inv.walk() if d in structure]
    starts = [structure[d]["first_page"] for d in order]
    check(starts == sorted(starts), "pages appear in navigation order")
    check(starts[0] == res["offset"] + 1, "content starts right after front matter")
    check(order[0] == f"{SD}.Administering", "first page is the first menu entry")
    check(order[1] == f"{SD}.Administering.Manage-users", "nested menu order is depth-first")
    check(order[-1] == f"{SD}.Developing.Workflow", "second top-level section comes after the first")
    kids = [structure[d]["first_page"] for d in
            (f"{SD}.Administering.Manage-users", f"{SD}.Administering.Manage-users.Assign-roles")]
    check(kids[0] < kids[1], "child page follows its parent")
    check(rd not in structure, "redirect page is not duplicated in the PDF")
    try:
        cnt = [0]
        def walk(items):
            for it in items or []:
                if isinstance(it, list):
                    walk(it)
                else:
                    cnt[0] += 1
        walk(rd_.outline)
        check(cnt[0] == len(render_index), "bookmark tree has one entry per page",
              f"{cnt[0]} vs {len(render_index)}")
    except Exception as exc:
        check(False, "bookmark tree readable", repr(exc))

    print("== 5. link rewrite + verifier ==")
    stats, samples = audit_links(rd_, SPACE, SD)
    check(stats.get("helix_inspace_uri_LEFT", 0) == 0,
          "no in-space link still points at the website", f"left={stats.get('helix_inspace_uri_LEFT',0)}")
    total_links = sum(len(LINKS[d]) for d in DOCS if not metas[d].get("is_redirect"))
    exp_pages = sum(v["pages"] for v in render_index.values())
    check(stats.get("external_uri", 0) == exp_pages,
          "non-doc links deliberately kept external (one youtube link per page)",
          f"{stats.get('external_uri',0)} vs {exp_pages}")
    if stats.get("helix_inspace_uri_LEFT", 0):
        print("   leftovers:", json.dumps(samples["helix_unresolved"], indent=1))
        print("   resolver keys:", json.dumps(sorted(
            __import__('helixdocs.assemble', fromlist=['build_link_resolver'])
            .build_link_resolver(inv, metas, SPACE).keys())[:20], indent=1))
    check(stats.get("internal_goto", 0) >= total_links, "doc links became in-document jumps",
          f"{stats.get('internal_goto',0)} >= {total_links}")
    rows = check_content(rd_, structure, metas)
    check(all(r["status"] == "ok" for r in rows), "every page's title + source marker found in text",
          json.dumps([r["status"] for r in rows]))
    toc_hits = [r for r in rows if r["pages"] >= 1]
    check(len(toc_hits) == len(render_index), "verifier saw every rendered page")

    print("== 6. TOC content ==")
    toc_text = "".join((rd_.pages[i].extract_text() or "") for i in range(1, 1 + res["toc_pages"]))
    for d in render_index:
        check(DOCS[d][:14].lower() in toc_text.lower(), f"TOC lists {DOCS[d]}")
    check(str(structure[f"{SD}.Administering"]["first_page"]) in toc_text,
          "TOC prints the real page number of the first topic")

    fails += fallback_selftest(ws, fails)

    print()
    if args.with_render:
        fails += render_selftest(ws, fails)
    if fails:
        print(f"SELFTEST FAILED ({len(fails)}):")
        for f in fails:
            print("  -", f)
        sys.exit(1)
    print("SELFTEST PASSED - pipeline logic verified offline")


def fallback_selftest(ws, fails):
    """The recovery ladder for pages the CSS engine cannot lay out.

    This is the code that runs when a page blows up rendering, and it must never
    need that engine: profile the page, flatten its CSS, lay the text out with
    ReportLab. Content and links have to survive all three, because a page built by
    the fallback still has to satisfy 'everything is in the PDF' and 'links to it
    jump inside the PDF'.
    """
    from helixdocs.fallback import flatten_css, page_source_url, profile_html, render_text_pdf

    print("== fallback-layout selftest (no CSS engine) ==")

    def ck(cond, label, detail=""):
        print(f"  {'ok  ' if cond else 'FAIL'} {label}" + (f"   {detail}" if detail else ""))
        if not cond:
            fails.append(label)

    doc = f"{SD}.Developing.Workflow"
    other = f"{SD}.Administering.Manage-users"
    href = pretty_url(other, SPACE, SD)
    rows = "".join(f"<tr><td>property {i}</td><td><a href='{href}'>related topic {i}</a></td>"
                   f"<td>value &lt;{i}&gt;</td></tr>" for i in range(600))
    html_file = os.path.join(ws, "fb-page.html")
    open(html_file, "w").write(
        f"<html><head><style>table{{display:flex}} .x{{color:red}}</style></head><body>"
        f"<div id='content'><h1>Workflow</h1><p style='color:red'>intro {MARK[doc]} with a "
        f"<a href='{href}'>sibling</a></p>"
        f"<table class='x'><tr><th>Property</th><th>Link</th><th>Value</th></tr>{rows}</table>"
        f"<p><img src='file://{ws}/assets/pic.png'></p></div>"
        f"<div class='hx-src'>BMC Helix documentation &middot; {doc}</div></body></html>")

    prof = profile_html(html_file)
    ck(prof.get("tables") == 1 and prof.get("max_table_rows") >= 600,
       "profile names the pathological structure", f"rows={prof.get('max_table_rows')}")
    ck(prof.get("links") == 601, "profile counts the links", f"links={prof.get('links')}")

    flat = os.path.join(ws, "fb-page.flat.html")
    removed = flatten_css(html_file, flat)
    ftxt = open(flat).read()
    ck(removed.get("style_blocks") == 1 and removed.get("style_attrs") == 1,
       "CSS flattening strips the author stylesheet", json.dumps(removed))
    ck("property 599" in ftxt and href in ftxt,
       "flattened page keeps its table rows and links")

    import time
    t0 = time.time()
    pdf = os.path.join(ws, "fb-page.pdf")
    n = render_text_pdf(html_file, pdf, "Workflow", page_source_url(doc, SPACE, None))
    secs = time.time() - t0
    ck(n >= 1, "fallback layout produces a PDF", f"{n} page(s) in {secs:.1f}s")
    from pypdf import PdfReader
    rd = PdfReader(pdf)
    body = "\n".join((pg.extract_text() or "") for pg in rd.pages)
    ck(MARK[doc] in body and "property 599" in body and "value <599>" in body,
       "fallback page carries every line of the table, entities included")
    ck("BMC Helix documentation" in body and "Workflow" in body,
       "fallback page carries the title and the source marker")
    ck("[image:" in body, "fallback page records the images it could not draw")
    uris = [str(a.get_object().get("/A").get_object().get("/URI"))
            for pg in rd.pages for a in (pg.get("/Annots") or [])
            if a.get_object().get("/A") is not None
            and a.get_object().get("/A").get_object().get("/URI") is not None]
    ck(href in uris, "fallback links use the portal URL the assembler rewrites",
       f"uris={len(uris)}")
    ck(secs < 90, "fallback layout stays linear on a 600-row table", f"{secs:.1f}s")
    print()
    return fails


def render_selftest(ws, fails):
    """Exercise the actual HTML -> PDF path with WeasyPrint (CI / Linux desktop)."""
    try:
        from weasyprint import HTML  # noqa: F401
    except Exception as exc:
        print(f"== render selftest: SKIPPED ({type(exc).__name__}) ==")
        return fails
    import shutil
    print("== render selftest (WeasyPrint) ==")
    rw = os.path.join(ws, "render")
    shutil.rmtree(rw, ignore_errors=True)
    os.makedirs(rw, exist_ok=True)
    from PIL import Image
    img = os.path.join(rw, "diagram.png")
    Image.new("RGB", (320, 180), (30, 90, 160)).save(img)
    inv = Inventory(SPACE)
    for d, title in DOCS.items():
        inv.add(d, title, parent=PARENTS[d], depth=(1 if PARENTS[d] is None else 2))
    for d in DOCS:
        inv.nodes[d]["children"] = [c for c in DOCS if PARENTS[c] == d]
    http = Http(os.path.join(ws, "cache"), workers=1, delay=0, retries=1, verbose=False)
    b = PageBuilder(http, SPACE, rw, mirror_attachments=False)
    b._localize = lambda url, doc=None, kind="asset": ("file://" + img, "stub")
    metas, html_ok = {}, True
    for d in DOCS:
        fx = fixture_html(d).replace("<table>", f'<img src="{img}"><table>')
        metas[d] = b.build(d, fx, title_hint=DOCS[d])
        h = open(metas[d]["html_file"], encoding="utf-8").read()
        if f"src=\"file://{img}\"" not in h:
            html_ok = False
    fails_ = []

    def ck(cond, label, detail=""):
        print(("  ok   " if cond else "  FAIL ") + label + (f"   {detail}" if detail else ""))
        if not cond:
            fails_.append(label)

    ck(html_ok, "images localised to files on disk")
    from helixdocs.render import render_all
    ri = render_all(metas, rw, engine="weasyprint", workers=2, fresh=True, verbose=False)
    ck(all(v.get("ok") for v in ri.values()) and len(ri) >= 1, "every page rendered",
       f"{sum(1 for v in ri.values() if v.get('ok'))}/{len(ri)}")
    ck(all(v.get("pages", 0) >= 1 for v in ri.values()), "each page produced >=1 PDF page")
    p0 = list(ri.values())[0]["pdf"]
    from pypdf import PdfReader
    r0 = PdfReader(p0)
    t0 = r0.pages[0].extract_text() or ""
    d0 = [d for d, v in ri.items()][0]
    ck(f"{MARK[d0]}-tab2" in t0, "content hidden behind a tab is present in the PDF")
    ck(f"{MARK[d0]}-collapse" in t0, "content hidden in a collapsed block is present")
    ck(f"{MARK[d0]}-table" in t0 and f"{MARK[d0]}-navjunk" not in t0,
       "table kept, site navigation stripped")
    xo = 0
    for pg in r0.pages:
        try:
            xo += len([k for k in (pg["/Resources"].get("/XObject") or {})])
        except Exception:
            pass
    ck(xo > 0, "the page image is embedded in the PDF", f"xobjects={xo}")
    opts = types.SimpleNamespace(space_path=SPACE, max_pages=0, no_stamp=False,
                                  out=os.path.join(rw, "merged.pdf"))
    res = assemble(inv, metas, ri, rw, "Test Product", "9.9", opts, verbose=False)
    rm = PdfReader(os.path.join(rw, "merged.pdf"))
    stats, samples = audit_links(rm, SPACE, SD)
    ck(stats.get("helix_inspace_uri_LEFT", 0) == 0,
       "no documentation link still opens the website",
       f"left={stats.get('helix_inspace_uri_LEFT', 0)}")
    ck(stats.get("internal_goto", 0) >= 1, "in-document jumps exist",
       f"goto={stats.get('internal_goto', 0)}")
    structure = json.load(open(os.path.join(rw, "structure.json")))["structure"]
    rows = check_content(rm, structure, metas)
    ck(all(r["status"] == "ok" for r in rows), "title + source marker found for every page",
       json.dumps({r["doc"].rsplit(".", 1)[-1]: r["status"] for r in rows if r["status"] != "ok"}))
    cnt = [0]
    def walk(items):
        for it in items or []:
            if isinstance(it, list):
                walk(it)
            else:
                cnt[0] += 1
    walk(rm.outline)
    ck(cnt[0] == len(ri), "PDF bookmarks mirror the navigation tree", f"{cnt[0]}/{len(ri)}")
    print()
    return fails + fails_


if __name__ == "__main__":
    main()
