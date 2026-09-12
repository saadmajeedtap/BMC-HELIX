# What the docs portal actually provides (measured 2026-09-11)

Evidence collected from `docs.helixops.ai` (BMC Helix Documentation, XWiki 16.10.11)
for `Service-Management/IT-Service-Management/BMC-Helix-ITSM/itsm263`.

## 1. The site's own "PDF" export cannot produce the whole manual

| Probe | Result |
|---|---|
| `GET /bin/pdf/<space>/WebHome` | 200, `application/pdf`, 73 431 bytes, **6 pages** (space landing page only) |
| `GET /bin/pdf/<space>/Navigating-common-interfaces/WebHome?includeAllChildren=true` | 200, **26 022 bytes, 3 pages** — byte-identical for `includeAllChildren`, `contentVisibility=all`, `includeAttachments`, `paper=A4`, `xpage=pdf`: the flag is ignored, so "this page and its children" does not work by URL |
| `POST /bin/export/<space>/WebHome` (`includeAllChildren=true&format=pdf`) | 200, 24 836 bytes, single page, producer `Apache FOP 2.3` |
| images inside those PDFs | `imgs=0` on pages that are mostly screenshots — the FOP export **drops images** |
| `GET /bin/export/...` (no POST) | 500 |

Conclusion: the vendor export = one page, no images — not "complete documentation".

## 2. The ready-made PDFs exist but need a BMC account

- `…/itsm263/PDFs-and-videos/` → "Videos and downloadable resources", body replaced by
  *`You must log in or register to view this page`*
- `/bin/attachments/…/PDFs-and-videos/` → 404, so the attachment list is not reachable
  anonymously either.
- Every product landing page links to that same page ("Get a list of all the videos and a
  PDF version of the … documentation").

If you have BMC SSO, downloading that official PDF is the cheapest path; this repo's
pipeline exists to get the same result (and better navigation) without an account.

## 3. Enumeration: how a complete inventory is obtained

- `sitemap.xml`, robots sitemap, `XWiki/query/rest/getChildren`, `getWikiSpaces`,
  `searchDocs`, `getAttachments` → 404 (XWiki REST is disabled for anonymous users).
- `?xpage=rdf` returns page content, not the tree.
- **Working:** the export dialog's own lazy tree endpoint, discovered in the rendered HTML:
  `/bin/get/<space>/WebHome?outputSyntax=plain&sheet=XWiki.ExportDocumentTree&filterHiddenDocuments=false&showTranslations=false&limit=10&root=document:xwiki:<space>.WebHome`
  plus BMC's `XWiki/BMC/CETS/Macros/Navigation/BmcDocumentTree?limit=50&root=document:xwiki:<space>.WebHome`.
  `?limit=` is honoured and `root=` selects the node, so a recursive walk yields every page
  of the space — that is `scripts/helixdocs/tree.py` (endpoint shapes are scraped at runtime,
  with fallbacks, so a portal upgrade cannot silently produce an empty PDF).
- A rendered page embeds only the *current* nav branch (13 unique in-space links on the
  landing page), so scraping nav alone would have missed pages — hence the tree API.

## 4. Link behaviour (why a downloaded PDF usually still "opens the web")

Inside the vendor PDF export, links are absolute — e.g.
`https://docs.helixops.ai/bin/Service-Management/…/Getting-started/Use-cases/Leveraging-BMC-HelixGPT-chat-to-search-for-information/`
(31 of 36 annotations in a sampled page) — and named destinations (`/Dests`) are absent.
That is exactly the "clicking the menu jumps to the website" symptom. Fixing it needs a
URL → in-document-destination map built during assembly, which is what
`scripts/helixdocs/assemble.py` does, with `scripts/helixdocs/verify.py` asserting that
`helix_inspace_uri_LEFT == 0`.

A second URL form hides in the nav of gated sections:

```
https://docs.helixops.ai/bin/login/XWiki/XWikiLogin?xredirect=/bin/<space>/PDFs-and-videos/
```

Four such links survived the first full build (to `PDFs-and-videos`, `Activity-testing`,
`Known-and-corrected-issues` and one `Use-cases` page) even though **all four pages were
already inside the PDF** - the wrapper simply did not match the URL -> doc map, so the
link stayed pointed at the website's login form. `config.unwrap_login_url()` now follows
the `xredirect` wherever a URL is mapped (`url_to_doc`, cleaning, and the assembler's
rewrite), which turns those four into in-document jumps. Gated *content* is still not
reachable anonymously; the pipeline records it rather than inventing it.

## 5. Other notes

- `/robots.txt` allows `/bin/<space>/…` reads and disallows `*/pdf/`, `*/tex/`,
  `*/edit/`, `*/save/`, `*/preview/` etc.; the pipeline only reads allowed
  view/download paths.
- Attachments and images are anonymously downloadable
  (`/bin/download/…` → 200 `image/svg+xml`), which lets the mirror embed figures.
- `/bin/<space>/` returns 200 with ~138 KB of HTML (content is public; only the
  downloads page is gated).
- `Agentic-AI-capabilities-in-BMC-Helix-ITSM/WebHome` returned **500** for the FOP export,
  so even per-page vendor export is not reliable across the space.


## Anonymous listing APIs: measured 2026-09-11 by `probe-endpoints`

Every shape below was requested from a GitHub-hosted runner (the sandbox has no
egress to the host, so all measurements are from CI, committed on `docs-probe`):

| Endpoint tried | Result |
|---|---|
| `/bin/get/<space>/WebHome?outputSyntax=plain&sheet=XWiki.ExportDocumentTree&root=...` | 404 (427-byte Tomcat error page) |
| same on `/bin/get/<space>/WebHome/`, `sheet=XWiki.PageTree`, `tree=1`, `xpage=rdf` | 404 |
| `/bin/get/XWiki/BMC/CETS/Macros/Navigation/BmcDocumentTree?limit=50&root=document%3A<space>.WebHome&outputSyntax=plain` — the URL the site writes into `data-url` on the live page | 404 plain, 404 with `X-Requested-With: XMLHttpRequest` + `Referer`, 404 with `limit=5000`, 404 without `exclusions` |
| `/query/rest/*` (getChildren, getLastModified, searchDocs), `/rest/suggest` | 404 |
| `/bin/search/main/?outputSyntax=plain` | 404 |
| `?xpage=livetable` | 200, empty body |
| `?xpage=print`, `&printSubpages=true`, `&includeAllChildren=true`, `?print=1` | 200 but exactly one page (97-120 KB, `contentTitle` count = 1) |
| `/bin/pdf/<space>/<section>/WebHome?includeAllChildren=true&printSubpages=true` | 200, 43 KB, image-free, still one page |
| `/bin/get/<space>/<section>/WebHome?outputSyntax=plain&includeAllChildren=true` | 200, 2.9 KB (the section page alone) |

Conclusion: no bulk or structured listing is available anonymously, so the
pipeline rebuilds the menu from the navigation markup each page already carries
(`nav_inventory`) and proves completeness by link closure. Pages are fetched
once and reused from cache by the fetch phase.

## 6. Measured result of a whole-space build (run 34695790103, 2026-09-12)

| | |
|---|---|
| pages in PDF | 1918 (496 documents, cover + TOC included) |
| size | 148.3 MB |
| coverage | 100 % (0 missing, 0 fetch failures, 0 thin pages) |
| links | 3965 in-document jumps, 1353 other-space + 250 external kept, 4 login-wrapped (fixed above) |
| timings | inventory 71 s, fetch 345 s (1650 requests, 0 errors), render 1305 s, assemble 12 s, verify 52 s |

The render time is dominated by one page: `Rebranding-BMC-Helix-ITSM-on-the-Universal-Client`
takes >240 s *and* >900 s in WeasyPrint with its author CSS, and renders in 24 s once the CSS
is flattened (19 pages, all text/tables/images/links kept). Its profile is what the report's
degraded section is for.
