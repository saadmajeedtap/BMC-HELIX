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
| The portal is XWiki 16.10.11 and its navigation is rendered **into each page** — but every machine-readable listing is closed to anonymous users | `probe-endpoints` run: `/bin/get/*` returns 404 for all 40 shapes tried, **including the URL the site itself puts in `data-url`**; `sitemap.xml`, `?xpage=rdf`, `/query/rest/*` → 404 ([docs/portal-findings.md](docs/portal-findings.md)) |
| The authoritative menu is therefore the `<ul>` tree inside each page's `#left-navigation` — nesting gives parent/child, DOM order gives menu order | `helixdocs/tree.py:nav_inventory`, asserted by `scripts/integration_test.py` ("nesting comes from the nav `<ul>` hierarchy", "top-level sections keep menu order") |
| `?xpage=pdf` and the Export→PDF dialog export **one page only** (`includeAllChildren` is ignored) | probed: identical 26 022-byte PDF for all 6 parameter sets |
| That server-side export is Apache FOP and **drops every image** (`imgs=0` on pages that are mostly screenshots) | `scripts/pdfstat.py` on the fetched PDFs |
| The ready-made "complete documentation" PDFs live on *Videos and downloadable resources*, which **requires a BMC login** (`You must log in or register to view this page`), and the attachments endpoint 404s anonymously | `…/itsm263/PDFs-and-videos/` → 200 but gated; `/bin/attachments/…` → 404 |
| So: a usable complete PDF has to be assembled from the real rendered pages | → this tool |

Because of that, the build does not "print the website". It rebuilds it.

## How the build works

```
inventory → fetch → render → assemble → verify
```

1. **inventory** — breadth-first over the space. For every page it reads the
   rendered left navigation (parent/child from `<ul>` nesting, menu order from DOM
   order, real titles) **and** every other in-space link the page contains, so
   pages hidden from the menu are still captured. Each page is fetched exactly once
   and stays in `http-cache/`, which is why phase 2 needs almost no network.
   `--prefer-tree-api` additionally cross-checks against the portal's own tree
   endpoint when one is reachable. `inventory.json` is the audit list,
   `tree-probe.json` the diagnostics.
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
workflow; every ~100 s the runner pushes `build/state.txt` (current phase, memory,
disk, live log tail) plus the reports to the **`docs-build`** branch, and with
`publish_release: true` the complete PDF + `attachments.zip` are attached to a GitHub
Release (split into `part-*` files with a `cat` line if a single upload is refused).
Because state is pushed *while it works*, a build that gets cancelled mid-flight is
still diagnosable: `bash scripts/watch_ci.sh` follows it live.

```json
{
  "space_path": "Service-Management/IT-Service-Management/BMC-Helix-ITSM/itsm263",
  "product": "BMC Helix ITSM", "version": "26.3",
  "phases": "inventory,fetch,render,assemble,verify",
  "only_sections": "", "max_docs": "0",
  "engine": "weasyprint", "workers": "3", "http_workers": "8", "delay": "0.08",
  "nav_batch": "60", "image_max_width": "1200", "image_quality": "72",
  "phase_timeout": "5400",
  "no_attachments": false, "no_stamp": false,
  "commit_pdf": true, "publish_release": true
}
```

Two ready-made profiles ship in the repo:

```bash
make ci-validate && git push ...   # .build-config.validate.json - 2 sections, 25 pages
make ci-full     && git push ...   # .build-config.full.json    - whole space, Release
bash scripts/watch_ci.sh           # live progress from the docs-build branch
```

`selftest --with-render` and `integration_test --full` run *before* the build in CI,
so a broken assumption fails in two minutes instead of two hours. If `assemble` is
killed on a very large space (the footer-stamp pass is the memory-hungry part), the
CI retries it with `--no-stamp` and says so in the report - the document stays
complete and internally linked, only the printed page numbers are absent.
### Locally (same pipeline, your machine, ~30-60 min for the whole space)

```bash
git clone https://github.com/saadmajeedtap/arena.git && cd arena

# Debian/Ubuntu: WeasyPrint needs pango/cairo + fonts
sudo apt-get update && sudo apt-get install -y \
  libpango-1.0-0 libpangocairo-1.0-0 libcairo2 fonts-dejavu-core fonts-liberation

./scripts/bootstrap.sh                      # venv + python deps + self-test

# prove the pipeline works on your machine before touching the portal (localhost mock):
make e2e-mock

# quick look first (one menu section, 15 pages), then the whole space:
make pdf SECTIONS=Getting-started MAX_DOCS=15 WORK=/tmp/helix-test
make pdf WORK=/tmp/helix

# equivalently, without make:
.venv/bin/python scripts/build_docs_pdf.py \
  --space-path Service-Management/IT-Service-Management/BMC-Helix-ITSM/itsm263 \
  --product "BMC Helix ITSM" --version 26.3 \
  --workspace /tmp/helix --out BMC-Helix-ITSM-26.3-complete.pdf \
  --report /tmp/helix/coverage-report.md
```

Result: `BMC-Helix-ITSM-26.3-complete.pdf` next to `/tmp/helix/coverage.md`
(read that file first: it states how many portal pages were found, how many are in
the PDF, and that no documentation link still points at the website).
`/tmp/helix/attachments/` holds every referenced attachment (zip/pdf/xlsx) with the
`attachments.json` sha256 manifest; `/tmp/helix/page-map.json` maps each topic to its
PDF page range.

Verify the two things you asked for - everything present, and no menu link escaping to the website:

```bash
.venv/bin/python - <<'PYCHK'
import sys
from pypdf import PdfReader
r = PdfReader(sys.argv[1] if len(sys.argv) > 1
              else "BMC-Helix-ITSM-26.3-complete.pdf")


def flat(o):
    for it in o:
        if isinstance(it, list):
            yield from flat(it)
        elif hasattr(it, "get_object"):
            yield it.get_object()


uri_portal = uri_other = jumps = 0
for pg in r.pages:
    for a in (pg.get("/Annots") or []):
        o = a.get_object()
        act = o.get("/A")
        uri = (act.get("/URI") if act is not None else None) or o.get("/URI")
        if uri:
            u = str(uri)
            if "docs.helixops.ai" in u or "/bin/Service-Management/" in u:
                uri_portal += 1
            else:
                uri_other += 1
        if o.get("/Dest") or (act is not None and act.get("/S") == "/GoTo"):
            jumps += 1
print("pages:            ", len(r.pages))
print("menu bookmarks:   ", sum(1 for x in flat(r.outline) if "/Title" in x))
print("in-document jumps:", jumps, "(every documentation link)")
print("links to website:", uri_portal, " <- must be 0")
print("other external links (kept on purpose):", uri_other)
PYCHK
```

The same assertions run inside the build and are written to `/tmp/helix/coverage.md`,
which is the file to read if a number above is not what you expect.

Requirements: Python 3.10+, network access to `docs.helixops.ai`, `pango/cairo`.
Phases are cached in `--workspace`, so a re-run only rebuilds what changed, and an
interrupted build resumes.

**A single page can never lose you the document.** WeasyPrint's layout can be driven
into a long spin by one page (a very wide or deeply nested table); that once cost a
build 80 minutes and its PDF. So a page that exceeds `--page-render-timeout` walks
down a ladder: serial retry under a shared `--slow-page-timeout` budget, then the same
page with its author CSS stripped, then a pure-Python layout that has no CSS engine to
hang on. Each rung keeps every word, table row and link, so the page is still in the
PDF and links to it still jump inside the document; only styling gets simpler. Any page
that needed a rung is listed in `coverage.md` with a structural profile of what choked
the engine, and counted as `rendered_degraded`.

Use `--engine chromium --retry-engine none` (after `./scripts/bootstrap.sh chromium`)
if you want browser-exact CSS, `--no-attachments` to skip mirroring files, `--delay
0.2` to be gentler on the portal.

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
