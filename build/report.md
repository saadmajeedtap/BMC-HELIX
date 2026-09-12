## build log
date: 2026-09-12T15:39:25Z  runner: x86_64  sections=ALL
args: --space-path Service-Management/IT-Service-Management/BMC-Helix-ITSM/itsm263 --product BMC Helix ITSM --version 26.3 --workspace /tmp/helix-build --out /tmp/helix-build/BMC-Helix-ITSM-26.3-complete.pdf --engine weasyprint --workers 4 --http-workers 10 --delay 0.06 --nav-batch 60 --image-max-width 1200 --image-quality 72
## system deps
fonts: 53  mem: 15989 MB
## python deps
weasyprint 70.0 | pypdf 6.18.1 | reportlab 5.0.1
## selftest (offline logic + engine semantics)
  ok   fallback links use the portal URL the assembler rewrites   uris=602
  ok   fallback layout stays linear on a 600-row table   0.7s


== render selftest (WeasyPrint) ==
  ok   images localised to files on disk
Annotation sizes differ: 2 vs. 0
Annotation sizes differ: 2 vs. 0
Annotation sizes differ: 2 vs. 0
Annotation sizes differ: 2 vs. 0
Annotation sizes differ: 2 vs. 0
Annotation sizes differ: 2 vs. 0
  ok   every page rendered   6/6
  ok   each page produced >=1 PDF page
  ok   content hidden behind a tab is present in the PDF
  ok   content hidden in a collapsed block is present
  ok   table kept, site navigation stripped
  ok   the page image is embedded in the PDF   xobjects=1
  ok   no documentation link still opens the website   left=0
  ok   in-document jumps exist   goto=28
  ok   title + source marker found for every page   {}
  ok   PDF bookmarks mirror the navigation tree   6/6

SELFTEST PASSED - pipeline logic verified offline
selftest: PASSED
## integration test (mock portal, end to end)
[15:39:50] inventory: {"method": "rendered-navigation", "pages": 9, "denied_filtered": 2, "expand_failures": 0, "roots": 1, "depth_histogram": {"1": 1, "2": 2, "3": 4, "4": 2}}
[15:39:50] pages to build: 7 (order=7)
[15:39:50] --max-docs: 4 inventoried page(s) recorded in capped.json and left out of this build on purpose
[15:39:50] fetching + cleaning 3 pages ...
[fetch] cleaned 3/3 pages (http stats: {'requests': 10, 'cache_hits': 3, 'errors': 0, 'retries': 0, 'bytes': 12753, 'seconds': 0.4, 'mb': 0.0})
[15:39:51] attachments mirrored: 1/1 files
[15:39:51] fetched: ok=3 redirect=0 http-fail=0 http={'requests': 10, 'cache_hits': 3, 'errors': 0, 'retries': 0, 'bytes': 12753, 'seconds': 0.4, 'mb': 0.0}
[15:39:51] DONE in 0s
  ok   --max-docs records the pages it left out   4 pages
  ok   a scoped run never crawls the rest of the space   ['Getting-started']
  ok   pages excluded by the cap are not reported as missing content   missing=0 capped=4
  ok   the report states how many pages a test build left out on purpose   4
  ok   …and scores coverage against what the run actually asked for   100.0
  ok   report text written   824 chars

== http politeness/cache ==
    {"requests": 17, "cache_hits": 9, "errors": 0, "retries": 0, "bytes": 19080, "seconds": 2.3, "mb": 0.0}
  ok   zero http errors on a clean run

INTEGRATION PASSED - enumeration, closure, cleaning and link mapping verified
integration: PASSED
## build phases
--- phase: inventory (started 15:39:52) ---
phase inventory rc=0 ended 15:41:02  |  [15:41:02] inventory: {"method": "rendered-navigation", "pages": 448, "denied_filtered": 0, "expand_failures": 0, "roots": 1, "depth_histogram": {"1": 1, "3": 153, "2": 37, "4": 158, "5": 64, "6": 17, "7": 5, "8": 7, "9": 6}} [15:41:02] pages to build: 448 (order=448) [15:41:02] DONE in 70s 
--- phase: fetch (started 15:41:03) ---
phase fetch rc=0 ended 15:46:42  |  [15:46:42] attachments mirrored: 15/15 files [15:46:42] fetched: ok=496 redirect=0 http-fail=0 http={'requests': 1650, 'cache_hits': 322, 'errors': 0, 'retries': 0, 'bytes': 90595534, 'seconds': 338.3, 'mb': 90.6} [15:46:42] DONE in 338s 
--- phase: render (started 15:46:43) ---
phase render rc=0 ended 15:58:53  |  [15:58:29] trying a CSS-flattened copy of 1 page(s) ... [15:58:53]   [flatten] ok: Rebranding-BMC-Helix-ITSM-on-the-Universal-Client -> 19 page(s) [15:58:53] DONE in 730s 
--- phase: assemble (started 15:58:54) ---
phase assemble rc=0 ended 15:59:07  |  [assemble] pages=1918 docs=496 internalized=3281 external_left=1603 out=/tmp/helix-build/BMC-Helix-ITSM-26.3-complete.pdf t=12s [15:59:07] PDF written: /tmp/helix-build/BMC-Helix-ITSM-26.3-complete.pdf (148.3 MB, 1918 pages) [15:59:07] DONE in 13s 
--- phase: verify (started 15:59:08) ---
phase verify rc=0 ended 16:00:02  |  [16:00:02] coverage: {"inventory_pages": 496, "fetch_failures": 0, "missing_from_pdf": 0, "thin_or_empty_pages": 0, "coverage_percent": 100.0} [16:00:02] DONE in 54s NOTE: 1 page(s) needed a fallback layout (their text, tables and links are complete; styling was simplified) - each one is named with a structural profile in coverage.md 

## live log tail
```
Annotation sizes differ: 1 vs. 0
Annotation sizes differ: 1 vs. 0
Annotation sizes differ: 5 vs. 0
Annotation sizes differ: 1 vs. 0
Annotation sizes differ: 2 vs. 0
Annotation sizes differ: 4 vs. 0
Annotation sizes differ: 2 vs. 0
Annotation sizes differ: 2 vs. 0
Annotation sizes differ: 2 vs. 0
Annotation sizes differ: 2 vs. 0
Annotation sizes differ: 2 vs. 0
Annotation sizes differ: 2 vs. 0
Annotation sizes differ: 2 vs. 0
Annotation sizes differ: 2 vs. 0
Annotation sizes differ: 2 vs. 0
[assemble] stamped 1909 content pages
[assemble] pages=1918 docs=496 internalized=3281 external_left=1603 out=/tmp/helix-build/BMC-Helix-ITSM-26.3-complete.pdf t=12s
[15:59:07] PDF written: /tmp/helix-build/BMC-Helix-ITSM-26.3-complete.pdf (148.3 MB, 1918 pages)
[15:59:07] DONE in 13s
=== phase verify ===
[15:59:09] pages to build: 496 (order=496)
[16:00:02] sample page images: 10
[16:00:02] coverage: {"inventory_pages": 496, "fetch_failures": 0, "missing_from_pdf": 0, "thin_or_empty_pages": 0, "coverage_percent": 100.0}
[16:00:02] DONE in 54s
NOTE: 1 page(s) needed a fallback layout (their text, tables and links are complete; styling was simplified) - each one is named with a structural profile in coverage.md
```

## results
```
{
 "pdf": "BMC-Helix-ITSM-26.3-complete.pdf",
 "pdf_bytes": 148268898,
 "inventory_pages": 496,
 "docs_in_pdf": 496,
 "pdf_pages": 1918,
 "rendered_ok": 496,
 "rendered_degraded": 1,
 "redirect_pages": 0,
 "fetch_failures": 0,
 "filtered_authoring_artifacts": 0,
 "missing_from_pdf": 0,
 "thin_or_empty_pages": 0,
 "not_built_by_request": 0,
 "coverage_base": 496,
 "coverage_percent": 100.0,
 "links": {
  "internal_goto": 3969,
  "helix_other_space_uri": 1353,
  "external_uri": 250
 },
 "expand_failures": 0,
 "build_seconds": 52.0,
 "engine": "weasyprint",
 "http": {
  "requests": 0,
  "cache_hits": 0,
  "errors": 0,
  "retries": 0,
  "bytes": 0,
  "seconds": 52.0,
  "mb": 0.0
 },
 "assets_mb": 52.1,
 "inventory": {
  "method": "rendered-navigation",
  "pages": 496,
  "denied_filtered": 0,
  "expand_failures": 0,
  "roots": 1,
  "depth_histogram": {
   "1": 1,
   "3": 153,
   "2": 85,
   "4": 158,
   "5": 64,
   "6": 17,
   "7": 5,
   "8": 7,
   "9": 6
  }
 }
}
```
missing_from_pdf: []
fetch_failures: []

```
total 148432
drwxr-xr-x  8 runner runner      4096 Sep 12 16:00 .
drwxrwxrwt 17 root   root        4096 Sep 12 15:46 ..
-rw-r--r--  1 runner runner 148268898 Sep 12 15:59 BMC-Helix-ITSM-26.3-complete.pdf
drwxr-xr-x  2 runner runner     69632 Sep 12 15:46 assets
drwxr-xr-x  2 runner runner      4096 Sep 12 15:46 attachments
-rw-r--r--  1 runner runner     12225 Sep 12 15:46 attachments.json
-rw-r--r--  1 runner runner         2 Sep 12 15:39 build-rc
-rw-r--r--  1 runner runner      7683 Sep 12 16:00 build.log
-rw-r--r--  1 runner runner      2752 Sep 12 15:58 cover.pdf
-rw-r--r--  1 runner runner      1160 Sep 12 16:00 coverage.json
-rw-r--r--  1 runner runner      5966 Sep 12 16:00 coverage.md
drwxr-xr-x  2 runner runner    323584 Sep 12 15:46 http-cache
-rw-r--r--  1 runner runner    653973 Sep 12 15:46 inventory.json
-rw-r--r--  1 runner runner         2 Sep 12 16:00 last-phase-rc
-rw-r--r--  1 runner runner    710652 Sep 12 15:46 metas.json
-rw-r--r--  1 runner runner    187223 Sep 12 16:00 page-map.json
drwxr-xr-x  2 runner runner    110592 Sep 12 15:58 pages
drwxr-xr-x  2 runner runner    110592 Sep 12 15:58 pdf
-rw-r--r--  1 runner runner    195732 Sep 12 15:58 render-index.json
-rw-r--r--  1 runner runner      6983 Sep 12 16:00 report.md
drwxr-xr-x  2 runner runner      4096 Sep 12 16:00 samples
-rw-r--r--  1 runner runner   1104642 Sep 12 15:59 stamps.pdf
-rw-r--r--  1 runner runner    116811 Sep 12 15:59 structure.json
142M	/tmp/helix-build/BMC-Helix-ITSM-26.3-complete.pdf
760K	/tmp/helix-build/attachments
```
excerpt: 52642071 bytes
samples.tgz: 1692 KB
attachments.zip: 578 KB
pdf bytes: 148268898
not committed (too big for git): BMC-Helix-ITSM-26.3-complete.pdf (142M)
committed to docs-build: attachments.zip (580K)
not committed (too big for git): excerpt.pdf (51M)
committed to docs-build: page-map.json (184K)
release: docs-bmc-helix-itsm-26.3-20260912-1600
