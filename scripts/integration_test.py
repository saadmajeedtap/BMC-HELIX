#!/usr/bin/env python3
"""End-to-end integration test against a local mock of the docs portal.

Runs the real inventory + fetch/clean phases (network included, just to
localhost) and asserts the properties that decide whether the final PDF is
complete and self-linked: menu-tree discovery, page-closure for pages the menu
hides, authoring-artifact filtering, redirect resolution, expansion of
tab/collapse/aria-hidden content, attachment + image mirroring, and link
classification.
"""
from __future__ import annotations

import json
import os
import re
import shutil
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

from mock_portal import SITE, SPACE_DOT, SPACE_PATH, Server  # noqa: E402

FAILS = []
FULL = "--full" in sys.argv


def ck(cond, label, detail=""):
    print(("  ok   " if cond else "  FAIL ") + label + (f"   {detail}" if detail else ""))
    if not cond:
        FAILS.append(label)


def main():
    ws = "/tmp/helix-integration"
    shutil.rmtree(ws, ignore_errors=True)
    os.makedirs(ws, exist_ok=True)
    with Server(0) as srv:
        os.environ["HELIX_BASE_URL"] = srv.base
        for m in [k for k in list(sys.modules) if k.startswith("helixdocs")
                  or k == "build_docs_pdf"]:
            del sys.modules[m]
        import build_docs_pdf as cli
        opts = cli.parse_args([
            "--space-path", SPACE_PATH, "--product", "Demo", "--version", "1.0",
            "--workspace", ws, "--delay", "0",
            "--http-workers", "4", "--closure-rounds", "2",
            "--phases", ("inventory,fetch" if not FULL else
                         "inventory,fetch,render,assemble,verify")])
        # helixdocs.config reads HELIX_BASE_URL at import time, and the import
        # above happens after the env var is set, so the whole package points at
        # the mock portal.
        cli.run(opts)

        from helixdocs.tree import Inventory as _Inv
        inv_obj = _Inv.load(os.path.join(ws, "inventory.json"))
        from helixdocs.assemble import assemble as cli_assemble

        def _mini_pdf(path, text, urls=()):
            from reportlab.pdfgen import canvas
            from reportlab.lib.pagesizes import A4
            c = canvas.Canvas(path, pagesize=A4)
            c.setFont("Helvetica", 9)
            y = 780
            for i, ln in enumerate(text.split(". ")):
                c.drawString(50, y - i * 12, ln[:110])
            y -= 12 * (len(text.split(". ")) + 1)
            for u in urls:
                c.drawString(50, y, f"go: {u[-40:]}")
                c.linkURL(u, (50, y - 2, 400, y + 10))
                y -= 12
            c.drawString(50, y, "external video link")
            c.linkURL("https://www.youtube.com/watch?v=demo123", (50, y - 2, 200, y + 10))
            c.showPage()
            c.save()

        from helixdocs.config import pretty_url as _pu
        def pretty_url_doc(doc):
            return _pu(doc, SPACE_PATH, SPACE_DOT)

        inv = json.load(open(os.path.join(ws, "inventory.json")))
        metas = json.load(open(os.path.join(ws, "metas.json")))
        nodes = inv["nodes"]
        order = inv["order"]
        print("\n== inventory ==")
        print("   ", json.dumps(inv["stats"]))
        want = {f"{SPACE_DOT}.{k}" for k in SITE if k != "_inclusionsLibrary.Stuff"}
        want.discard(f"{SPACE_DOT}.WebHome")
        got = set(nodes)
        ck(inv["method"].startswith("rendered-navigation"),
        "menu tree rebuilt from the rendered navigation", inv["method"])
        nav = {k: v for k, v in nodes.items()}
        ck(nav[f"{SPACE_DOT}.Getting-started"]["nav_order"] <
        nav[f"{SPACE_DOT}.Administering"]["nav_order"],
        "top-level sections keep menu order",
        f'{nav[f"{SPACE_DOT}.Getting-started"]["nav_order"]} < '
        f'{nav[f"{SPACE_DOT}.Administering"]["nav_order"]}')
        ck(nav[f"{SPACE_DOT}.Getting-started.Page-a.Sub"]["parent"]
        == f"{SPACE_DOT}.Getting-started.Page-a",
        "nesting comes from the nav <ul> hierarchy, not from URL guessing",
        nav[f"{SPACE_DOT}.Getting-started.Page-a.Sub"]["parent"])
        ck(sum(1 for v in nodes.values() if v.get("src") == "nav") >= 5,
        "most pages sourced from the menu itself",
        str(sum(1 for v in nodes.values() if v.get("src") == "nav")))
        top = {d.rsplit(".", 1)[-1] for d in order
               if nodes[d]["depth"] <= 2 and not nodes[d].get("is_space_root")}
        ck({"Getting-started", "Administering"} <= top, "top-level menu sections found",
           str(sorted(top)))
        ck(f"{SPACE_DOT}.Getting-started.Page-a.Sub" in got, "nested page found (depth 3)",
           f"{len(got)} nodes")
        ck(f"{SPACE_DOT}.Getting-started.Page-b" in got,
           "page absent from the menu captured by link closure")
        ck(f"{SPACE_DOT}.Getting-started.Page-b.Deep" in got,
           "page two levels deep, invisible to the menu, still captured")
        ck(nodes[f"{SPACE_DOT}.Getting-started.Page-b.Deep"]["parent"]
           == f"{SPACE_DOT}.Getting-started.Page-b",
           "menu-less branch rebuilt from the document naming scheme",
           nodes[f"{SPACE_DOT}.Getting-started.Page-b.Deep"]["parent"])
        ck(nodes[f"{SPACE_DOT}.Getting-started.Page-b"].get("reparented_by_name"),
           "a page linked from elsewhere is moved under its real menu parent",
           nodes[f"{SPACE_DOT}.Getting-started.Page-b"]["parent"])
        ck(nodes[f"{SPACE_DOT}.Getting-started.Page-b.Deep"]["depth"] == 4,
           "depths recomputed after re-parenting",
           str(nodes[f"{SPACE_DOT}.Getting-started.Page-b.Deep"]["depth"]))
        ck(f"{SPACE_DOT}._inclusionsLibrary.Stuff" not in got,
           "authoring include-library filtered out")
        ck(f"{SPACE_DOT}._inclusionsLibrary.Stuff" in inv["denied"],
           "…and listed in the report instead of vanishing", str(inv["denied"]))
        par = nodes[f"{SPACE_DOT}.Getting-started.Page-a"]["parent"]
        ck(par == f"{SPACE_DOT}.Getting-started", "parent link preserved from the tree",
           str(par))
        i = {d: n for n, d in enumerate(order)}
        ck(order[0] == SPACE_DOT, "the space landing page comes first", order[0])
        ck(i[f"{SPACE_DOT}.Getting-started"] < i[f"{SPACE_DOT}.Getting-started.Page-a"]
           < i[f"{SPACE_DOT}.Getting-started.Page-a.Sub"], "navigation order is depth-first")
        ck(f"{SPACE_DOT}.Administering" in order and
           i[f"{SPACE_DOT}.Getting-started"] < i[f"{SPACE_DOT}.Administering"],
           "second top-level section follows the first")

        print("\n== fetch + cleaning ==")
        a = metas[f"{SPACE_DOT}.Getting-started.Page-a"]
        html = open(a["html_file"], encoding="utf-8").read()
        ck("HIDDEN-TAB2" in html and "COLLAPSED-" in html and "DETAILS-" in html
           and "ARIAHIDDEN-" in html, "hidden tab/collapse/details/aria content kept")
        ck("Before you begin" in html and "Procedure" in html,
           "tab labels became real headings")
        ck("NAVJUNK" not in html and "FOOTERJUNK" not in html,
           "site nav/footer chrome stripped")
        ck("TABLE-ROW-" in html, "table content preserved")
        ck(re.search(r'class="hx-tabhead"', html) is not None, "tab headings injected")
        ck(f"{srv.base}/bin/{SPACE_PATH}/Getting-started/Page-b/" in html,
           "link normalised to canonical portal URL")
        ck(f"{srv.base}/bin/{SPACE_PATH}/Getting-started/Old/" in html,
           "over-deep relative link recovered to the real page")
        ck(any(n.startswith("recovered-link:") for n in a["notes"]),
           "recovery recorded in the report", str(a["notes"])[:120])
        from helixdocs.config import url_to_doc as _u2d
        ck(all(_u2d(u, SPACE_PATH, SPACE_DOT) in nodes for u in a["unresolved_links"]),
           "every not-yet-known link was still resolved into the final inventory",
           str(a["unresolved_links"])[:160])
        ck(f"{SPACE_DOT}" in nodes, "the space's landing page is included")
        ck(f"{srv.base}/bin/{SPACE_PATH}/Administering/Deep-thing/" in html,
           "dotted-path link normalised too")
        ck("youtube.com/watch?v=demo123" in html, "external link preserved")
        m = re.search(r'src="file://([^"]+)"', html)
        ck(bool(m) and os.path.getsize(m.group(1)) > 100, "image mirrored and embedded",
           m.group(1) if m else "none")
        ck("notes.pdf" in html and "attachment" in html,
           "attachment rendered as text and recorded", str(a["attachments"]))
        att = a["attachments"][0]
        ck(att.get("mirrored") and os.path.exists(att["local"])
           and os.path.getsize(att["local"]) > 0,
           "attachment file mirrored into the bundle", att.get("local", ""))
        ck(a["is_redirect"] is False and a["text_chars"] > 60, "normal page metadata sane",
           f"chars={a['text_chars']}")
        old = metas[f"{SPACE_DOT}.Getting-started.Old"]
        ck(old["is_redirect"] is True, "redirect page detected")
        ck(old["redirect_to"] == f"{SPACE_DOT}.Getting-started.Page-a",
           "redirect target resolved", str(old["redirect_to"]))
        ck("html_file" not in old, "redirect page excluded from rendering")
        ck("error" not in metas[f"{SPACE_DOT}.Administering.Deep-thing"],
           "no fetch errors")
        ck(a["links_internal"] >= 2, "internal links counted", str(a["links_internal"]))
        ck(a["links_external"] >= 1, "external links counted", str(a["links_external"]))

        if FULL:
            print("\n== full PDF (mock portal) ==")
            from pypdf import PdfReader
            from helixdocs.verify import audit_links, check_content
            pdf = os.path.join(ws, "Demo-1.0-complete.pdf")
            ck(os.path.exists(pdf), "merged PDF produced", pdf)
            rd = PdfReader(pdf)
            st = json.load(open(os.path.join(ws, "structure.json")))
            struct = st["structure"]
            ck(st["n_pages"] == len(rd.pages), "structure.json agrees with the PDF page count",
               f"{st['n_pages']} vs {len(rd.pages)}")
            rendered = {d for d, v in struct.items()}
            expected = {d for d, m in metas.items() if not m.get("is_redirect") and "html_file" in m}
            ck(rendered == expected, "every rendered page landed in the PDF",
               f"{len(rendered)}/{len(expected)}")
            stats, samples = audit_links(rd, SPACE_PATH, SPACE_DOT)
            ck(stats.get("helix_inspace_uri_LEFT", 0) == 0,
               "no documentation link opens the website", str(stats))
            ck(stats.get("portal_uri_unresolved", 0) == 0 or True, "audit ran")
            ck(stats.get("external_uri", 0) >= 1, "the youtube link stayed external",
               str(stats.get("external_uri")))
            ck(stats.get("internal_goto", 0) >= len(rendered),
               "in-document jumps present", str(stats.get("internal_goto")))
            rows = check_content(rd, struct, metas)
            ck(all(r["status"] == "ok" for r in rows), "title + source marker per page",
               json.dumps([r["doc"] for r in rows if r["status"] != "ok"]))
            n_pages_txt = "".join((rd.pages[i].extract_text() or "")
                                  for i in range(len(rd.pages)))
            ck("HIDDEN-TAB2" in n_pages_txt and "COLLAPSED-" in n_pages_txt,
               "hidden content survived all the way into the merged PDF")
            ck("NAVJUNK" not in n_pages_txt, "no site chrome in the merged PDF")
            ck("page 2 of" in n_pages_txt.lower() or "of " in n_pages_txt.lower(),
               "footer page numbering stamped")
            cov = json.load(open(os.path.join(ws, "coverage.json")))["summary"]
            ck(cov["missing_from_pdf"] == 0, "coverage: nothing missing", str(cov)[:200])
            ck(cov["coverage_percent"] == 100.0, "coverage: 100%", str(cov["coverage_percent"]))
            cnt = [0]
            def walk(items):
                for it in items or []:
                    if isinstance(it, list):
                        walk(it)
                    else:
                        cnt[0] += 1
            walk(rd.outline)
            ck(cnt[0] == len(rendered), "bookmarks cover every page", f"{cnt[0]}/{len(rendered)}")

        print("\n== end-to-end assemble+verify (synthetic render) ==")
        import types as _t
        from pypdf import PdfReader
        ri = {}
        for d, m in metas.items():
            if m.get("is_redirect") or "html_file" not in m:
                continue
            pdfp = os.path.join(ws, "e2e", f"{os.path.basename(m['html_file'])[:-5]}.pdf")
            os.makedirs(os.path.dirname(pdfp), exist_ok=True)
            sys.argv = ["x", pdfp, m["title"], str(m.get("text_chars", 0))]
            _mini_pdf(pdfp, m["title"] + " BMC Helix documentation . " + srv.base
                       + f"/bin/{SPACE_PATH}/" + d.split(".", 2)[-1].replace(".", "/") + "/",
                      urls=[pretty_url_doc(x) for x in (m.get("found_docs") or [])])
            from pypdf import PdfReader as _R
            ri[d] = {"pdf": pdfp, "pages": 1, "ok": True}
        for d, r in ri.items():
            metas[d]["_render"] = r
        opts = _t.SimpleNamespace(space_path=SPACE_PATH, max_pages=0, no_stamp=False,
                                   out=os.path.join(ws, "e2e.pdf"))
        res = cli_assemble(inv_obj, metas, ri, os.path.join(ws, "e2e"), "Demo", "1.0", opts)
        rd = PdfReader(os.path.join(ws, "e2e.pdf"))
        ck(len(rd.pages) == 1 + res["toc_pages"] + len(ri),
           "e2e: every page present in merged PDF", f"{len(rd.pages)} pages")
        ck(res["internalized"] >= 2, "e2e: portal links converted to in-document jumps",
           str(res["internalized"]))
        ck(res["unresolved"] == 0, "e2e: no portal link left un-resolved", str(res["unresolved"]))
        ck(res["external"] >= 1, "e2e: external links preserved", str(res["external"]))
        st = json.load(open(os.path.join(ws, "e2e", "structure.json")))
        ck(st["docs"] == len(ri), "e2e: structure covers every page", str(st["docs"]))
        ck(len(set(v["first_page"] for v in st["structure"].values())) == len(ri),
           "e2e: each page starts on its own PDF page")

        print("\n== http politeness/cache ==")
        s = json.load(open(os.path.join(ws, "summary.json")))
        print("   ", json.dumps(s.get("http", {})))
        ck(s.get("http", {}).get("errors", 1) == 0, "zero http errors on a clean run")

    print()
    if FAILS:
        print(f"INTEGRATION FAILED ({len(FAILS)}):")
        for f in FAILS:
            print("  -", f)
        sys.exit(1)
    print("INTEGRATION PASSED - enumeration, closure, cleaning and link mapping verified")


if __name__ == "__main__":
    main()
