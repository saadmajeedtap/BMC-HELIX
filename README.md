# BMC Helix ITSM 26.3 — complete documentation as one offline PDF

Goal: take `https://docs.helixops.ai/bin/Service-Management/IT-Service-Management/BMC-Helix-ITSM/itsm263/`
and produce **one PDF containing every page of that documentation space**, where
clicking any navigation item or cross-reference **jumps inside the PDF** instead of
opening the website.

This repository contains the tool that does it, plus the CI workflow that runs it
with internet access and publishes the result.

---

## What the portal actually offers (measured, not assumed)

| Finding | Evidence |
|---|---|
| The portal is XWiki 16.10.11; page tree is served lazily by `XWiki.ExportDocumentTree` / BMC's `BmcDocumentTree` | scraped from live HTML ([docs/portal-findings.md](docs/portal-findings.md)) |
| `?xpage=pdf` and the Export→PDF dialog export **one page only** (`includeAllChildren` is ignored) | probed: identical 26 022-byte PDF for all 6 parameter sets |
| That server-side export is Apache FOP and **drops every image** (`imgs=0` on pages that are mostly screenshots) | `scripts/pdfstat.py` on the fetched PDFs |
| The ready-made "complete documentation" PDFs live on *Videos and downloadable resources*, which **requires a BMC login** (`You must log in or register to view this page`), and the attachments endpoint 404s anonymously | `…/itsm263/PDFs-and-videos/` → 200 but gated; `/bin/attachments/…` → 404 |
| So: a usable complete PDF has to be assembled from the real rendered pages | → this tool |

Because of that, the build does not "print the website". It rebuilds it.

## How the build works

```
inventory → fetch → render → assemble → verify
```

1. **inventory** — walks the portal's own document-tree API to exhaustion (the same
   endpoint the site's *Export ▸ PDF* dialog uses to decide what belongs to a
   space), then adds every extra page found by following links, so pages missing
   from the menu are still captured. `tree-probe.json` records which endpoint
   shape was used, `inventory.json` is the audit list.
2. **fetch** — downloads the rendered HTML of every page (polite, cached,
   resumable), then cleans it: strips site chrome, and **expands everything the
   site hides** — tab panes, collapsed/accordion blocks, `style="display:none"`,
   `aria-hidden`, `<details>` — each hidden tab gets a real heading so nothing is
   lost. Images are mirrored to disk and embedded; attachments are optionally
   mirrored into the bundle. Every link to a page of this space is normalised to
   its canonical portal URL so step 4 can resolve it, and links to *other* BMC
   spaces are kept as ordinary external links (and reported).
3. **render** — each documentation page becomes its own PDF via WeasyPrint
   (A4, print CSS, `pypdf` page counts). Exact per-page ranges are what make the
   link/TOC/coverage work provable rather than approximate. Pages that WeasyPrint
   can't lay out are automatically re-rendered with headless Chromium.
4. **assemble** — merges in navigation order and then:
   - cover page + **table of contents with real page numbers** (clickable),
   - **PDF bookmarks = the website's menu tree** (and `PageMode /UseOutlines`, so
     the panel opens by itself — that is the "navigation menu" inside the PDF),
   - rewrites *every* link that pointed at `docs.helixops.ai` (and legacy
     `docs.bmc.com/xwiki` equivalents) into an **in-document jump**, resolving
     redirect/moved pages to their new location,
   - footer stamp with the global page number, the section and the product/version,
     plus a plain-text source line on each page so any line can be traced back.
5. **verify** — the completeness proof: inventory vs. PDF, per-page text checks,
   and a full annotation audit that fails the build if a single in-space link is
   still a web URL. Output: `coverage.md`, `coverage.json`, `page-map.json`
   (every page → its PDF page range, char count), `excerpt.pdf` + sample PNGs.

Nothing is silently skipped: filtered authoring artifacts (`_inclusionsLibrary`,
`WebPreferences`, XWiki classes/templates) are counted and listed in the report.

## Run it

### In CI (recommended — needs internet + can publish the big file)

`.build-config.json` controls a build. Pushing a change to that file starts the
workflow; results land on the `docs-build` branch (reports, page map, excerpt, and
the PDF itself when it fits in git) and, with `publish_release: true`, the complete
PDF is attached to a GitHub Release.

```json
{
  "space_path": "Service-Management/IT-Service-Management/BMC-Helix-ITSM/itsm263",
  "product": "BMC Helix ITSM", "version": "26.3",
  "phases": "inventory,fetch,render,assemble,verify",
  "only_sections": "", "engine": "weasyprint",
  "publish_release": true
}
```

Set `"only_sections": "Getting-started"` for a fast sample build, `"max_docs": "30"`
for a smoke test.

### Locally

```bash
./scripts/bootstrap.sh          # venv + deps (needs libpango/cairo for WeasyPrint)
make pdf                        # or:
.venv/bin/python scripts/build_docs_pdf.py \
    --workspace /tmp/helix --out BMC-Helix-ITSM-26.3-complete.pdf \
    --report /tmp/helix/coverage-report.md
open /tmp/helix/coverage.md
```

Requirements: Python 3.10+, network access to `docs.helixops.ai`, `pango/cairo`
(for WeasyPrint) and optionally Playwright's Chromium. Use
`--engine chromium --retry-engine none` if you want browser-exact CSS.

Other spaces work the same way — e.g. `--space-path
Service-Management/IT-Service-Management/BMC-Helix-ITSM-Service-Desk/servicedesk263`.

## Checks

```bash
python3 scripts/selftest.py                # offline: cleaning, links, merge, TOC, verifier
python3 scripts/selftest.py --with-render  # + real WeasyPrint engine (needs pango)
python3 scripts/probe_docs_site.sh         # what the portal allows (read-only)
python3 scripts/pdfstat.py <file.pdf>      # pages / outline / links / images of any PDF
```

## Ground rules

Public documentation, fetched read-only, from the documented view/download paths
only (`robots.txt` disallows the `edit/`, `save/`, `pdf/`, `viewrev/` actions —
those are never requested), with a single shared throttle (`--delay`) and a
identifying User-Agent. Intended for personal/offline use; redistribute as BMC's
licence allows. `make lint` runs a syntax pass over the tooling.
