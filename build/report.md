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
