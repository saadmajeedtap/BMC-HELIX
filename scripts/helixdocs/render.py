"""Render each cleaned page to its own PDF.

Two engines:
  weasyprint (default) - pure python, exact page counts, deterministic, no browser.
  chromium             - pixel-faithful CSS via headless Chrome, for pages where
                         WeasyPrint's layout support is not enough.
Rendering one PDF per documentation page keeps the page-range of every topic exact,
which is what makes the internal-link/TOC/coverage work provable, and it makes the
build resumable (a page that is already rendered is skipped).
"""
from __future__ import annotations

import json
import os
import time

SIZE_MM = {"A4": (210, 297), "Letter": (215.9, 279.4)}


def _wp_worker(args):
    slug, html_file, pdf_file, page_size, margin_mm, scale = args
    try:
        from weasyprint import HTML
        doc = HTML(filename=html_file).render()
        n = len(doc.pages)
        doc.write_pdf(pdf_file)
        return slug, {"pages": n, "ok": True}
    except Exception as exc:
        return slug, {"ok": False, "error": f"{type(exc).__name__}: {exc}"}


def render_weasyprint(jobs, workers=3):
    """jobs: list of (slug, html_file, pdf_file, page_size, margin_mm, scale)."""
    if not jobs:
        return {}
    res = {}
    try:
        from concurrent.futures import ProcessPoolExecutor
        with ProcessPoolExecutor(max_workers=max(1, workers)) as ex:
            for slug, r in ex.map(_wp_worker, jobs, chunksize=8):
                res[slug] = r
    except Exception as exc:  # multiprocessing unavailable -> serial
        print(f"[render] process pool unavailable ({exc}); running serial", flush=True)
        for j in jobs:
            slug, r = _wp_worker(j)
            res[slug] = r
    return res


def _chromium_worker(jobs, workers):
    import asyncio
    from playwright.async_api import async_playwright

    async def main():
        out = {}
        async with async_playwright() as pw:
            browser = await pw.chromium.launch(args=["--no-sandbox", "--font-render-hinting=none"])
            ctx = await browser.new_context()
            sem = asyncio.Semaphore(workers)
            ppage = SIZE_MM.get(jobs[0][3], SIZE_MM["A4"])

            async def one(slug, html_file, pdf_file, page_size, margin_mm, scale):
                async with sem:
                    try:
                        page = await ctx.new_page()
                        await page.goto("file://" + os.path.abspath(html_file))
                        try:
                            await page.wait_for_load_state("networkidle", timeout=8000)
                        except Exception:
                            pass
                        await page.emulate_media(media="print")
                        await page.pdf(path=pdf_file, width=f"{ppage[0]}mm",
                                       height=f"{ppage[1]}mm", print_background=True,
                                       margin={k: f"{margin_mm}mm" for k in
                                               ("top", "bottom", "left", "right")},
                                       scale=scale)
                        await page.close()
                        from pypdf import PdfReader
                        out[slug] = {"ok": True,
                                     "pages": len(PdfReader(pdf_file).pages)}
                    except Exception as exc:
                        out[slug] = {"ok": False, "error": repr(exc)}
            await asyncio.gather(*(one(*j) for j in jobs))
            await browser.close()
        return out

    return asyncio.run(main())


def render_all(metas, out_dir, engine="weasyprint", workers=3, page_size="A4",
               margin_mm=14, scale=0.92, fresh=False, limit=0, verbose=True):
    """Render every page that has HTML; returns {doc: {pdf, pages, ok, error}}."""
    pdf_dir = os.path.join(out_dir, "pdf")
    os.makedirs(pdf_dir, exist_ok=True)
    index_path = os.path.join(out_dir, "render-index.json")
    index = json.load(open(index_path)) if os.path.exists(index_path) else {}
    jobs = []
    done_now = {}
    n = 0
    for doc, meta in metas.items():
        if not meta or "html_file" not in meta:
            continue
        if meta.get("is_redirect"):
            continue
        slug = os.path.splitext(os.path.basename(meta["html_file"]))[0]
        pdf_file = os.path.join(pdf_dir, f"{slug}.pdf")
        if not fresh and os.path.exists(pdf_file) and os.path.getsize(pdf_file) > 900 \
                and os.path.getmtime(pdf_file) > os.path.getmtime(meta["html_file"]):
            try:
                from pypdf import PdfReader
                pages = len(PdfReader(pdf_file).pages)
                done_now[doc] = {"pdf": pdf_file, "pages": pages, "ok": True, "cached": True}
                continue
            except Exception:
                pass
        jobs.append((doc, slug, meta["html_file"], pdf_file))
        n += 1
        if limit and n >= limit:
            break
    if verbose:
        print(f"[render] engine={engine} to_render={len(jobs)} cached={len(done_now)}",
              flush=True)
    t0 = time.time()
    res = dict(done_now)
    if jobs:
        if engine == "weasyprint":
            raw = render_weasyprint([(slug, hf, pf, page_size, margin_mm, scale)
                                     for _doc, slug, hf, pf in jobs], workers)
        else:
            raw = _chromium_worker([(slug, hf, pf, page_size, margin_mm, scale)
                                    for _doc, slug, hf, pf in jobs], workers)
        for doc, slug, hf, pf in jobs:
            r = raw.get(slug) or {"ok": False, "error": "no-result"}
            res[doc] = {"pdf": pf, "pages": r.get("pages", 0), "ok": r.get("ok", False),
                        "error": r.get("error")}
    bad = [d for d, v in res.items() if not v["ok"]]
    if verbose:
        print(f"[render] ok={len(res)-len(bad)} failed={len(bad)} "
              f"pages={sum(v['pages'] for v in res.values())} t={time.time()-t0:.0f}s",
              flush=True)
        if bad:
            print(f"[render] failures: {bad[:10]}", flush=True)
    index.update({d: v for d, v in res.items()})
    json.dump(index, open(index_path, "w"), indent=1)
    return res
