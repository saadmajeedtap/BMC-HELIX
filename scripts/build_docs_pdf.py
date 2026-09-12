#!/usr/bin/env python3
"""Build a single, complete, self-linked PDF from a BMC Helix documentation space.

Example
-------
    python3 scripts/build_docs_pdf.py \
        --space-path Service-Management/IT-Service-Management/BMC-Helix-ITSM/itsm263 \
        --product "BMC Helix ITSM" --version 26.3 \
        --workspace /tmp/helix --out BMC-Helix-ITSM-26.3-complete.pdf

Pipeline (each phase is cached, so it is resumable):
  inventory  enumerate every page of the space with the portal's own document-tree
             API (the same one its "Export > PDF" dialog uses) + follow links to
             catch pages that the menu does not show.
  fetch      download each page's HTML, expand tabs/accordions/hidden blocks,
             mirror images and attachments, rewrite links.
  render     WeasyPrint (or headless Chromium) -> one PDF per documentation page.
  assemble   merge in navigation order, add cover + page-numbered table of
             contents + bookmarks, turn every in-space link into an in-document
             jump, stamp global page numbers.
  verify     prove completeness (inventory vs. PDF), audit every link, write
             coverage.json / coverage.md, rasterise sample pages.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from helixdocs.assemble import assemble                                  # noqa: E402
from helixdocs.config import (DEFAULT_PRODUCT, DEFAULT_SPACE_PATH,        # noqa: E402
                              DEFAULT_VERSION, is_denied, norm_doc, pretty_url, url_to_doc)
from helixdocs.net import Http                                            # noqa: E402
from helixdocs.page import PageBuilder, fetch_pages                       # noqa: E402
from helixdocs.render import engine_available, render_all                 # noqa: E402
from helixdocs.tree import (Inventory, _in_scope, bfs_inventory,             # noqa: E402
                            build_inventory, nav_inventory)
from helixdocs.verify import (audit_links, check_content, make_samples,   # noqa: E402
                              write_reports)

EXTRA_PARENT = "__additional-pages-not-in-navigation__"


def log(msg):
    print(f"[{time.strftime('%H:%M:%S')}] {msg}", flush=True)


def parse_args(argv=None):
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--space-path", default=os.environ.get("HELIX_SPACE", DEFAULT_SPACE_PATH))
    ap.add_argument("--product", default=os.environ.get("HELIX_PRODUCT", DEFAULT_PRODUCT))
    ap.add_argument("--version", default=os.environ.get("HELIX_VERSION", DEFAULT_VERSION))
    ap.add_argument("--workspace", default="build/helix")
    ap.add_argument("--out", default="")
    ap.add_argument("--report", default="", help="write a markdown summary here too")
    ap.add_argument("--phases", default="inventory,fetch,render,assemble,verify")
    ap.add_argument("--engine", default="weasyprint", choices=["weasyprint", "chromium"])
    ap.add_argument("--retry-engine", default="chromium",
                    choices=["none", "chromium", "weasyprint"],
                    help="engine used to re-render pages the first engine failed on")
    ap.add_argument("--workers", type=int, default=3, help="render processes")
    ap.add_argument("--http-workers", type=int, default=8)
    ap.add_argument("--delay", type=float, default=0.08, help="seconds between requests")
    ap.add_argument("--tree-limit", type=int, default=500)
    ap.add_argument("--enumerate-cap", type=int, default=40000,
                    help="max pages to discover (0 = no limit)")
    ap.add_argument("--nav-batch", type=int, default=60,
                    help="pages fetched per enumeration round (bounds memory)")
    ap.add_argument("--prefer-tree-api", action="store_true",
                    help="cross-check the menu with the portal's own tree API")
    ap.add_argument("--only-sections", default="", help="comma list of top-level sections")
    ap.add_argument("--max-docs", type=int, default=0, help="cap (for test builds)")
    ap.add_argument("--max-pages", type=int, default=0,
                    help="cap the number of merged documentation pages (0 = all)")
    ap.add_argument("--fresh", action="store_true", help="ignore HTTP/render caches")
    ap.add_argument("--page-render-timeout", type=int, default=240,
                    help="seconds a single page may take in WeasyPrint before it is "
                         "deferred to the retry engine and reported (0 = unlimited)")
    ap.add_argument("--no-image-optimize", action="store_true",
                    help="keep portal images byte-for-byte (bigger PDF, exact source)")
    ap.add_argument("--image-max-width", type=int, default=1400,
                    help="resample mirrored images wider than this (0 = never)")
    ap.add_argument("--image-quality", type=int, default=80, help="JPEG quality")
    ap.add_argument("--no-attachments", action="store_true",
                    help="do not mirror non-image attachments")
    ap.add_argument("--no-assets", action="store_true", help="skip images (fast, ugly)")
    ap.add_argument("--no-stamp", action="store_true", help="skip footer/page-number stamp")
    ap.add_argument("--skip-verify-samples", action="store_true")
    ap.add_argument("--closure-rounds", type=int, default=2)
    ap.add_argument("--inventory", default="", help="reuse an inventory.json (skips phase 1)")
    ap.add_argument("--time-budget", type=int, default=0,
                    help="stop after N seconds and build what was fetched")
    ap.add_argument("--smoke-page", default="",
                    help="fetch one live URL, run the cleaning rules, print what survived")
    return ap.parse_args(argv)


def prune_sections(inv, only):
    keep = set()
    wanted = {w.strip().lower().replace(" ", "-") for w in only if w.strip()}
    if not wanted:
        return inv
    # a section is a menu entry directly under the space (or a top-level root)
    roots = {d: (inv.nodes[d]["title"] or "").lower().replace(" ", "-")
             for d in inv.nodes
             if inv.nodes[d].get("depth", 1) <= 2 and not inv.nodes[d].get("is_space_root")}
    top = [d for d, t in roots.items() if t in wanted or any(w in t for w in wanted)]
    for d in top:
        stack = [d]
        while stack:
            cur = stack.pop()
            keep.add(cur)
            stack.extend(inv.nodes[cur]["children"])
    if inv.space_dot in inv.nodes:
        keep.add(inv.space_dot)
    inv.nodes = {d: n for d, n in inv.nodes.items() if d in keep}
    for n in inv.nodes.values():
        if n["parent"] not in inv.nodes:
            n["parent"] = None
        n["children"] = [c for c in n["children"] if c in inv.nodes]
    return inv


def run(opts):
    ws = os.path.abspath(opts.workspace)
    os.makedirs(ws, exist_ok=True)
    phases = [p.strip() for p in opts.phases.split(",") if p.strip()]
    inv_path = os.path.join(ws, "inventory.json")
    metas_path = os.path.join(ws, "metas.json")
    out_pdf = opts.out or os.path.join(ws, f"{opts.product.replace(' ', '-')}-{opts.version}-complete.pdf")
    t_start = time.time()

    http = Http(os.path.join(ws, "http-cache"), workers=opts.http_workers,
                delay=opts.delay, fresh=opts.fresh)

    # ------------------------------------------------------------- 1 inventory
    if "inventory" in phases:
        if opts.inventory and os.path.exists(opts.inventory):
            inv = Inventory.load(opts.inventory)
            log(f"inventory loaded from {opts.inventory}: {len(inv.nodes)} pages")
        else:
            log("enumerating the space: every page, following the portal's own "
                "rendered navigation and all in-space links (link closure) ...")
            only = [x for x in (opts.only_sections or "").split(",") if x.strip()]
            inv = nav_inventory(http, opts.space_path,
                                max_pages=opts.enumerate_cap or 10 ** 9,
                                time_budget=opts.time_budget or None,
                                verbose=True, only=only or None,
                                batch=opts.nav_batch)
            if opts.prefer_tree_api:      # optional cross-check against the site API
                diag = os.path.join(ws, "tree-probe.json")
                try:
                    t_inv = build_inventory(http, opts.space_path, limit=opts.tree_limit,
                                            time_budget=opts.time_budget or None,
                                            diag_path=diag, only=only or None)
                    extra = [d for d in t_inv.nodes if d not in inv.nodes]
                    for d in extra:
                        t = t_inv.nodes[d]
                        inv.add(d, t["title"], parent=t["parent"], depth=t["depth"])
                    if extra:
                        log(f"tree API contributed {len(extra)} pages the crawl missed")
                    inv.method += "+tree-api"
                except Exception as exc:
                    log(f"tree API cross-check unavailable: {exc}")
            def _ord(c, _inv=inv):
                v = _inv.nodes.get(c, {}).get("nav_order")
                return (v if isinstance(v, int) else 10 ** 9,
                        _inv.nodes.get(c, {}).get("title", "").lower())

            for n in inv.nodes.values():  # menu order decides the final sequence
                n["children"] = sorted(dict.fromkeys(n.get("children") or []), key=_ord)
            inv.save(inv_path)
        log(f"inventory: {json.dumps(inv.stats())}")
    else:
        inv = Inventory.load(inv_path)
    inv = prune_sections(inv, opts.only_sections.split(","))
    log(f"pages to build: {len(inv.nodes)} (order={len(inv.walk())})")

    # ------------------------------------------------------------ 2 fetch/clean
    builder = PageBuilder(http, opts.space_path, ws,
                          mirror_attachments=not opts.no_attachments,
                          optimize_images=not opts.no_image_optimize,
                          image_max_width=opts.image_max_width,
                          image_quality=opts.image_quality,
                          known_docs=set(inv.nodes), parent_map={
                              d: n.get("parent") for d, n in inv.nodes.items()})
    metas = {}
    if "fetch" in phases:
        todo = inv.walk()
        if opts.max_docs:
            dropped = todo[opts.max_docs:]
            todo = todo[:opts.max_docs]
            if dropped:
                json.dump(dropped, open(os.path.join(ws, "capped.json"), "w"))
                log(f"--max-docs: {len(dropped)} inventoried page(s) recorded in "
                    f"capped.json and left out of this build on purpose")
        builder.known_docs = set(inv.nodes)
        builder.parent_map = {d: n.get("parent") for d, n in inv.nodes.items()}
        log(f"fetching + cleaning {len(todo)} pages ...")
        metas = fetch_pages(http, inv, builder, todo)
        # link-closure sweep: pages that exist but are not in the menu
        for rnd in range(opts.closure_rounds):
            found = set()
            for d, m in metas.items():
                if m:
                    found.update(m.get("found_docs") or [])
                    for fd in (m.get("filtered_refs") or []):   # auditable, not silent
                        if fd not in inv.nodes and fd not in inv.denied:
                            inv.denied.append(fd)
            new = [d for d in found
                   if d and d not in inv.nodes and not is_denied(d)
                   and d.startswith(inv.space_dot)
                   and _in_scope(d, inv.space_dot,
                                 {w.strip().lower().replace(" ", "-")
                                  for w in opts.only_sections.split(",") if w.strip()}
                                 or None)]
            if not new:
                break
            log(f"closure round {rnd+1}: {len(new)} page(s) reachable by link but "
                f"not in the navigation tree -> added")
            root_parent = inv.space_dot if inv.space_dot in inv.nodes else EXTRA_PARENT
            for d in new:
                inv.add(d, d.rsplit(".", 1)[-1].replace("-", " "), parent=root_parent,
                        depth=inv.nodes.get(root_parent, {}).get("depth", 1) + 1)
            if root_parent == EXTRA_PARENT:  # no space root: keep them visible anyway
                inv.nodes.setdefault(EXTRA_PARENT, {
                    "doc": EXTRA_PARENT, "title": "Additional pages (linked, not in menu)",
                    "parent": None, "depth": 1, "children": sorted(new), "closed": False,
                    "url": "", "slug": "additional"})
            extra_meta = fetch_pages(http, inv, builder, sorted(new))
            metas.update(extra_meta)
            for d2, m2 in extra_meta.items():   # second-order discovery
                if m2:
                    found.update(m2.get("found_docs") or [])
        metas = {d: m for d, m in metas.items() if m is not None}
        json.dump(metas, open(metas_path, "w"))
        inv.save(inv_path)   # persist the inventory *including* closure additions
        n_att = write_attachment_manifest(metas, ws)
        log(f"attachments mirrored: {n_att}")
        ok = sum(1 for m in metas.values() if "error" not in m)
        red = sum(1 for m in metas.values() if m.get("is_redirect"))
        log(f"fetched: ok={ok} redirect={red} http-fail={len(metas)-ok-red} "
            f"http={http.summary()}")
    elif os.path.exists(metas_path):
        metas = json.load(open(metas_path))
    elif set(phases) & {"render", "assemble", "verify"}:
        raise SystemExit("no metas.json - run the fetch phase first")

    # ----------------------------------------------------------------- 3 render
    render_index = {}
    if "render" in phases:
        log(f"rendering pages with {opts.engine} ...")
        render_index = render_all(metas, ws, engine=opts.engine, workers=opts.workers,
                                  fresh=opts.fresh, limit=opts.max_docs or 0,
                                  verbose=True, page_timeout=opts.page_render_timeout)
        bad = [d for d, v in render_index.items() if not v.get("ok")]
        if bad and (opts.retry_engine == "none" or not engine_available(opts.retry_engine)):
            # A page can legitimately need longer than the per-page cap (a 4 000-row
            # table). Losing it is worse than being slow, so retry those pages one at
            # a time with no time limit - the phase timeout is still the backstop.
            log(f"re-rendering {len(bad)} slow page(s) serially with no page timeout ...")
            slow = {d: metas[d] for d in bad if d in metas}
            render_index.update(render_all(slow, ws, engine=opts.engine, workers=1,
                                           fresh=True, page_timeout=0, verbose=True))
            render_index = {d: v for d, v in render_index.items()}
            bad = [d for d, v in render_index.items() if not v.get("ok")]
            if bad:
                log(f"{len(bad)} page(s) still unrendered; they are listed in the report")
        if bad and opts.retry_engine != "none" and opts.retry_engine != opts.engine \
                and engine_available(opts.retry_engine):
            log(f"re-rendering {len(bad)} failed page(s) with {opts.retry_engine} ...")
            for d in bad:
                p = render_index[d].get("pdf")
                if p and os.path.exists(p):
                    os.remove(p)
            only = {d: metas[d] for d in bad if d in metas}
            render_index.update(render_all(only, ws, engine=opts.retry_engine,
                                           workers=opts.workers, fresh=True,
                                           page_timeout=0))
    else:
        ri = os.path.join(ws, "render-index.json")
        render_index = json.load(open(ri)) if os.path.exists(ri) else {}
    for d, r in render_index.items():
        if d in metas:
            metas[d]["_render"] = r

    # --------------------------------------------------------------- 4 assemble
    summary = {}
    if "assemble" in phases:
        log("merging, linking, building contents/bookmarks ...")
        summary = assemble(inv, metas, render_index, ws, opts.product, opts.version, opts)
        if os.path.abspath(summary["out_pdf"]) != os.path.abspath(out_pdf):
            os.replace(summary["out_pdf"], out_pdf)
        log(f"PDF written: {out_pdf} ({os.path.getsize(out_pdf)/1e6:.1f} MB, "
            f"{summary['pages']} pages)")

    # ----------------------------------------------------------------- 5 verify
    report_md = ""
    if "verify" in phases:
        from pypdf import PdfReader
        rd = PdfReader(out_pdf)
        structure = json.load(open(os.path.join(ws, "structure.json")))["structure"]
        stats, samples = audit_links(rd, opts.space_path, inv.space_dot)
        rows = check_content(rd, structure, metas)
        capped_path = os.path.join(ws, "capped.json")
        skip_docs = set(json.load(open(capped_path))) if os.path.exists(capped_path) else set()
        extra = {"build_seconds": round(time.time() - t_start, 1),
                 "engine": opts.engine, "http": http.summary(),
                 "assets_mb": round(_dir_mb(os.path.join(ws, "assets")), 1)}
        summary2, report_md = write_reports(ws, inv, metas, render_index, structure,
                                            stats, samples, rows, out_pdf, extra,
                                            pdf_pages=len(rd.pages), skip_docs=skip_docs)
        summary.update(summary2)
        if not opts.skip_verify_samples:
            idx = [0, 1] + sorted(set([r["page"] for r in rows[::max(1, len(rows)//8)]]))[:8]
            pngs = make_samples(out_pdf, os.path.join(ws, "samples"), idx)
            log(f"sample page images: {len(pngs)}")
        log("coverage: " + json.dumps({k: v for k, v in summary.items()
                                       if k in ("coverage_percent", "inventory_pages",
                                                "pages_in_pdf", "missing_from_pdf",
                                                "thin_or_empty_pages", "fetch_failures")}))
    if opts.report and report_md:
        open(opts.report, "w").write(report_md + "\n")
    summary.setdefault("http", http.summary())
    summary.setdefault("inventory", inv.stats())
    json.dump(summary, open(os.path.join(ws, "summary.json"), "w"), indent=1)
    log(f"DONE in {time.time()-t_start:.0f}s")
    return summary


def write_attachment_manifest(metas, ws):
    """List every attachment referenced by the documentation, with its hash, so the
    mirrored bundle can be checked file by file (and gaps seen, not hidden)."""
    import hashlib
    items, kept = [], 0
    for d, m in sorted(metas.items()):
        for att in (m.get("attachments") or []):
            rec = {"doc": d, "name": att["name"], "url": att["url"],
                   "mirrored": bool(att.get("mirrored")), "local": att.get("local", "")}
            lp = att.get("local")
            if lp and os.path.exists(lp):
                rec["bytes"] = os.path.getsize(lp)
                h = hashlib.sha256()
                with open(lp, "rb") as fh:
                    for chunk in iter(lambda: fh.read(1 << 20), b""):
                        h.update(chunk)
                rec["sha256"] = h.hexdigest()[:32]
                kept += 1
            else:
                rec["bytes"] = 0
                rec["missing_reason"] = "not mirrored" if not att.get("mirrored") else "file gone"
            items.append(rec)
    json.dump({"total": len(items), "mirrored": kept,
               "bytes": sum(i["bytes"] for i in items), "items": items},
              open(os.path.join(ws, "attachments.json"), "w"), indent=1)
    return f"{kept}/{len(items)} files"


def _dir_mb(path):
    tot = 0
    for _r, _d, fs in os.walk(path):
        for f in fs:
            try:
                tot += os.path.getsize(os.path.join(_r, f))
            except Exception:
                pass
    return tot / 1e6


def smoke(url):
    """Run the real cleaning pipeline over one live page and report on it."""
    from helixdocs.config import space_dot as _sd
    from helixdocs.page import PageBuilder
    h = Http("/tmp/helix-smoke/http", workers=1, delay=0)
    r = h.get(url)
    if r is None or r[0] != 200:
        print(f"smoke: could not fetch {url}: {r}")
        return 1
    space = opts_space_from_url(url)
    inv = Inventory(space)
    doc = url_to_doc(url, space, _sd(space)) or inv.space_dot
    b = PageBuilder(h, space, "/tmp/helix-smoke/out", mirror_attachments=True)
    meta = b.build(doc, r[1])
    out = {k: v for k, v in meta.items() if k not in ("html_file",)}
    print("smoke doc:", doc)
    print("meta:", json.dumps(out, indent=1)[:2600])
    html = open(meta["html_file"], encoding="utf-8").read()
    print(f"html: {len(html)} bytes; images localised: {meta['images']}; "
          f"tables: {meta['tables']}; internal links: {meta['links_internal']}; "
          f"external: {meta['links_external']}")
    for probe in ("xwiki:content", "collapse", "tab-pane", "display:none"):
        print(f"  contains {probe!r}: {probe in html}")
    print("written:", meta["html_file"])
    return 0


def opts_space_from_url(url):
    m = re.search(r"/bin/(?:view/)?(Service-Management/[^/]+/[^/]+/[^/]+|[^/]+/[^/]+/[^/]+)", url)
    return m.group(1) if m else DEFAULT_SPACE_PATH


if __name__ == "__main__":
    opts = parse_args()
    if opts.smoke_page:
        sys.exit(smoke(opts.smoke_page))
    try:
        s = run(opts)
    except Exception as exc:
        import traceback
        traceback.print_exc()
        print(f"\nBUILD FAILED: {type(exc).__name__}: {exc}", flush=True)
        sys.exit(2)
    hard_fail = s.get("missing_from_pdf", 0) or s.get("fetch_failures", 0)
    left = s.get("links", {}).get("helix_inspace_uri_LEFT", 0) if isinstance(s.get("links"), dict) \
        else s.get("helix_inspace_uri_LEFT", 0)
    capped = s.get("not_built_by_request", 0) or 0
    if hard_fail or (left and not capped):
        print(f"BUILD INCOMPLETE: missing={s.get('missing_from_pdf')} "
              f"fetch_failures={s.get('fetch_failures')} unresolved_links={left}",
              flush=True)
        sys.exit(3)
    if left and capped:
        print(f"NOTE: {left} in-space link(s) still point at the portal because "
              f"{capped} page(s) were excluded by --max-docs; a full build resolves "
              f"them to in-document jumps", flush=True)
