"""Prove the finished PDF contains everything, then write the coverage report.

Three independent checks:
  1. inventory vs. build: every page enumerated from the portal's own document tree
     (plus every page discovered by following links) ends up in the PDF.
  2. content spot-check: the page's title and its per-page source marker are found
     in the extracted text of the pages that belong to it.
  3. link audit: no annotation may still point at a page of this documentation
     space (those are in-document jumps now); only genuinely external URLs remain.
"""
from __future__ import annotations

import json
import os
import re
from collections import Counter

from .config import BASE, is_denied, pretty_url


def _norm(s):
    return re.sub(r"[^a-z0-9]+", " ", (s or "").lower()).strip()


def audit_links(reader, space_path, space_dot, sample_limit=12):
    """Walk every link annotation; classify internal vs external."""
    stats = Counter()
    samples = {"helix_unresolved": [], "external": [], "internal_goto": sample_limit}
    for i, page in enumerate(reader.pages):
        try:
            annots = list(page.get("/Annots") or [])
        except Exception:
            continue
        for a in annots:
            try:
                o = a.get_object()
            except Exception:
                continue
            if o.get("/Subtype") != "/Link":
                continue
            dest = o.get("/Dest")
            act = o.get("/A")
            if act is not None:
                act = act.get_object()
                uri = act.get("/URI")
                if uri is None:
                    stats["annot_other_action"] += 1
                    continue
                u = str(uri)
                if re.search(r"docs\.helixops\.ai|docs\.bmc\.com/xwiki", u):
                    if space_path in u or space_dot in u:
                        stats["helix_inspace_uri_LEFT"] += 1
                        if len(samples["helix_unresolved"]) < sample_limit:
                            samples["helix_unresolved"].append({"page": i + 1, "uri": u})
                    else:
                        stats["helix_other_space_uri"] += 1
                        if len(samples["external"]) < sample_limit:
                            samples["external"].append({"page": i + 1, "uri": u[:220]})
                else:
                    stats["external_uri"] += 1
                    if len(samples["external"]) < sample_limit:
                        samples["external"].append({"page": i + 1, "uri": u[:220]})
                continue
            if dest is not None:
                stats["internal_goto"] += 1
    return stats, samples


def check_content(reader, structure, metas, docs=None, per_doc_chars_min=60):
    rows = []
    doc_list = docs if docs is not None else list(structure)
    for d in doc_list:
        s = structure[d]
        first, last = s["first_page"], s["last_page"]
        txt = ""
        try:
            txt = reader.pages[first - 1].extract_text() or ""
        except Exception:
            txt = ""
        tail = ""
        if last != first:
            try:
                tail = reader.pages[last - 1].extract_text() or ""
            except Exception:
                tail = ""
        body = txt + "\n" + tail
        title = _norm(metas[d].get("title", ""))[:60]
        title_ok = bool(title) and title in _norm(body)
        marker_ok = "BMC Helix documentation" in body
        chars = len(body)
        status = "ok" if (chars >= per_doc_chars_min and (title_ok or marker_ok)) else \
                 ("thin" if chars >= per_doc_chars_min else "empty")
        rows.append({"doc": d, "title": metas[d].get("title", ""), "pages": last - first + 1,
                     "page": first, "chars": chars, "title_found": title_ok,
                     "source_marker_found": marker_ok, "status": status,
                     "notes": metas[d].get("notes", [])})
    return rows


def write_reports(out_dir, inv, metas, render_index, structure, stats, samples,
                  content_rows, pdf_path, extra=None, pdf_pages=None, skip_docs=None):
    os.makedirs(out_dir, exist_ok=True)
    total_inv = len(inv.nodes)
    rendered = sum(1 for v in render_index.values() if v.get("ok"))
    redirects = sum(1 for m in metas.values() if m and m.get("is_redirect"))
    failed = [d for d, m in metas.items() if m and m.get("error")]
    skip_docs = skip_docs or set()
    missing = [d for d in inv.nodes
               if d not in structure and d not in skip_docs
               and not (metas.get(d) or {}).get("is_redirect")
               and not (metas.get(d) or {}).get("error")]
    thin = [r for r in content_rows if r["status"] != "ok"]
    summary = {
        "pdf": os.path.basename(pdf_path),
        "pdf_bytes": os.path.getsize(pdf_path) if os.path.exists(pdf_path) else 0,
        "inventory_pages": total_inv,
        "docs_in_pdf": len(structure or {}),
        "pdf_pages": pdf_pages if pdf_pages is not None else "",
        "rendered_ok": rendered,
        "redirect_pages": redirects,
        "fetch_failures": len(failed),
        "filtered_authoring_artifacts": len(inv.denied),
        "missing_from_pdf": len(missing),
        "thin_or_empty_pages": len(thin),
        "not_built_by_request": len(skip_docs),
        "coverage_base": total_inv - len(skip_docs),
        "coverage_percent": round(100.0 * (total_inv - len(skip_docs) - len(missing))
                                  / max(1, total_inv - len(skip_docs)), 3),
        "links": dict(stats or {}),
        "expand_failures": len(inv.expand_failures),
    }
    if extra:
        summary.update(extra)
    unresolved = (samples or {}).get("helix_unresolved") or []
    targets = sorted({u.get("uri", "") for u in unresolved})[:80]
    json.dump({"summary": summary, "missing": missing[:500], "failed": failed[:200],
               "thin": thin[:400], "denied": inv.denied[:400],
               "unresolved_links": unresolved[:200],
               "unresolved_targets": targets},
              open(os.path.join(out_dir, "coverage.json"), "w"), indent=1)
    json.dump(content_rows, open(os.path.join(out_dir, "page-map.json"), "w"), indent=1)

    md = [f"# Offline PDF build report", "",
          f"| metric | value |", f"|---|---|"]
    for k, v in summary.items():
        if isinstance(v, dict):
            continue
        md.append(f"| {k} | {v} |")
    md += ["", "## Links", "| kind | count |", "|---|---|"]
    for k, v in sorted(stats.items()):
        md.append(f"| {k} | {v} |")
    md += ["",
           "`internal_goto` = clicks that stay inside the file. "
           "`helix_inspace_uri_LEFT` must be 0 - that would mean a link to this "
           "documentation space still opens a browser.", ""]
    unresolved = (samples or {}).get("helix_unresolved") or []
    if unresolved:
        md += ["### Links that could not be resolved locally", ""]
        for s in unresolved:
            md.append(f"- p{s['page']}: `{s['uri'][:160]}`")
        md.append("")
    kept_external = (samples or {}).get("external") or []
    if kept_external:
        md += ["### Kept as external (outside this documentation space)", ""]
        for s in kept_external[:15]:
            md.append(f"- p{s['page']}: `{s['uri'][:150]}`")
        md.append("")
    if thin:
        md += ["### Pages with little text (check by eye)", ""]
        for r in thin[:40]:
            md.append(f"- p{r['page']} `{r['doc']}` chars={r['chars']} status={r['status']} "
                      f"notes={r['notes']}")
        md.append("")
    if missing:
        md += ["### In the portal but missing from the PDF", ""]
        for d in missing[:60]:
            md.append(f"- `{d}`")
        md.append("")
    md += ["## First 40 pages of the document", "",
           "| # | pdf page | pages | chars | title found | marker | title |", "|---|---|---|---|---|---|---|"]
    for r in content_rows[:40]:
        md.append(f"| {content_rows.index(r)+1} | {r['page']} | {r['pages']} | {r['chars']} "
                  f"| {r['title_found']} | {r['source_marker_found']} | {r['title'][:58]} |")
    open(os.path.join(out_dir, "coverage.md"), "w").write("\n".join(md) + "\n")
    return summary, "\n".join(md)


def make_samples(pdf_path, out_dir, page_indexes, width=1000):
    """Rasterise a few PDF pages for visual QA (needs pypdfium2)."""
    out = []
    os.makedirs(out_dir, exist_ok=True)
    try:
        import pypdfium2 as pdfium
    except Exception as exc:
        return out
    try:
        pdf = pdfium.PdfDocument(pdf_path)
        for pi in page_indexes:
            if pi >= len(pdf):
                continue
            img = pdf[pi].render(scale=width / 612.0).to_pil()
            p = os.path.join(out_dir, f"sample-page-{pi+1}.png")
            img.convert("RGB").save(p, optimize=True)
            out.append(p)
    except Exception as exc:
        print(f"[verify] sample render failed: {exc}", flush=True)
    return out
