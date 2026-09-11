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
