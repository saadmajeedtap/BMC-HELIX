#!/usr/bin/env bash
# Enumeration + whole-section-dump endpoint matrix for the XWiki docs portal.
# Read-only GET/HEAD probes. For each response we print status, size and the
# number of document titles it contains - a count > 1 means "multi-page dump",
# which would be a far cheaper way to get the whole space than page-by-page.
BASE="https://docs.helixops.ai"
S="Service-Management/IT-Service-Management/BMC-Helix-ITSM/itsm263"
SD="$S"; SD="${SD//\//.}"
SEC="Getting-started"
export BASE S SD SEC

hdr() { printf '\n%s\n' "## $*"; }

python3 - <<'PY'
import os, re, sys, json
import requests

BASE = os.environ["BASE"]; S = os.environ["S"]; SD = os.environ["SD"]; SEC = os.environ["SEC"]
S2 = requests.Session()
S2.headers["User-Agent"] = "Mozilla/5.0 (X11; Linux x86_64) probe"

def hdr(t):
    print(f"\n## {t}")


def probe(label, url, note=""):
    try:
        r = S2.get(url, timeout=90)
    except Exception as e:
        print(f"- **{label}** EXC {e!r}"); return
    body = r.text or ""
    titles = len(re.findall(r'id="contentTitle"', body))
    h1 = len(re.findall(r"<h1[\s>]", body))
    anchors = len(set(re.findall(r"/bin/(?:view/)?" + re.escape(S) + r"/[A-Za-z0-9._/-]+/", body)))
    magic = body[:8].replace("\n", " ")
    kind = "PDF" if r.content[:4] == b"%PDF" else ("JSON" if body.lstrip()[:1] in "[{" else "html")
    print(f"- **{label}** `{r.status_code}` {kind} bytes={len(r.content)} "
          f"contentTitle={titles} h1={h1} uniq-links={anchors} {note}")
    if titles > 1 or len(r.content) > 400000 or kind == "JSON":
        print(f"    url: {url}")
    if body.lstrip()[:1] in "[{" or titles > 1:
        print("    ```")
        print("    " + re.sub(r"\s+", " ", body)[:700])
        print("    ```")

hdr("0. does the live page still expose a tree endpoint URL (raw, unescaped)?")
seed = S2.get(f"{BASE}/bin/{S}/WebHome/", timeout=90)
html = seed.text.replace("&#38;", "&").replace("&amp;", "&")
print(f"- landing page `{seed.status_code}` bytes={len(seed.text)}")
urls = sorted(set(re.findall(r'/bin/get/[^ \t"\'<>]*(?:Tree|tree)[^ \t"\'<>]*', html)))
print(f"- {len(urls)} tree-ish URLs found in the HTML:")
for u in urls[:8]:
    print(f"    - {u[:300]}")
dataattrs = sorted(set(re.findall(r'data-(?:url|reference|root|tree)[^ >]{0,120}', html)))[:8]
print("- data-* attrs:", dataattrs)

hdr("1. ExportDocumentTree variants")
for root in (f"document%3Axwiki%3A{SD}.WebHome", f"document%3A{SD}.WebHome", SD + ".WebHome"):
    for tail in ("", "/"):
        probe(f"export-sheet root={root[:34]}{'/slash' if tail else 'noslash'}",
              f"{BASE}/bin/get/{S}/WebHome{tail}?outputSyntax=plain&sheet=XWiki.ExportDocumentTree"
              f"&filterHiddenDocuments=false&showTranslations=false&limit=50&root={root}")
probe("export-sheet on view action",
      f"{BASE}/bin/view/{S}/WebHome?outputSyntax=plain&sheet=XWiki.ExportDocumentTree&limit=50"
      f"&root=document%3Axwiki%3A{SD}.WebHome")
probe("BmcDocumentTree (as embedded)",
      f"{BASE}/bin/get/XWiki/BMC/CETS/Macros/Navigation/BmcDocumentTree?limit=50&outputSyntax=plain"
      f"&root=document%3Axwiki%3A{SD}.WebHome")
probe("BmcDocumentTree reference=",
      f"{BASE}/bin/get/XWiki/BMC/CETS/Macros/Navigation/BmcDocumentTree?limit=50&outputSyntax=plain"
      f"&reference=document%3Axwiki%3A{SD}.WebHome")
probe("BmcPageTree macro jsx",
      f"{BASE}/bin/get/XWiki/BMC/CETS/Macros/Navigation/BmcPageTree?limit=50"
      f"&root=document%3Axwiki%3A{SD}.WebHome&outputSyntax=plain")
probe("PageTree sheet",
      f"{BASE}/bin/get/{S}/WebHome/?outputSyntax=plain&sheet=XWiki.PageTree&limit=50"
      f"&root=document%3Axwiki%3A{SD}.WebHome")
probe("tree ajax (xwiki-tree)",
      f"{BASE}/bin/get/{S}/WebHome/?outputSyntax=plain&tree=1&root={SD}.WebHome")
probe("space doc list via get (no sheet)",
      f"{BASE}/bin/get/{S}/WebHome/?outputSyntax=plain")

hdr("2. whole-section dumps: print / pdf with subpages")
for q in ("?xpage=print", "?xpage=print&printSubpages=true", "?xpage=print&printSubpages=1",
          "?xpage=print&includeAllChildren=true", "?print=1", "?print=1&printSubpages=1",
          "?xpage=pdf&includeAllChildren=true&contentVisibility=all"):
    probe(f"section {SEC} {q}", f"{BASE}/bin/view/{S}/{SEC}/WebHome{q}")
probe("section pdf action + subpages",
      f"{BASE}/bin/pdf/{S}/{SEC}/WebHome?printSubpages=true&includeAllChildren=true&format=pdf")
probe("space print root", f"{BASE}/bin/print/{S}/WebHome")
probe("space print section", f"{BASE}/bin/print/{S}/{SEC}/WebHome")
probe("section plain all children",
      f"{BASE}/bin/get/{S}/{SEC}/WebHome?outputSyntax=plain&includeAllChildren=true")

hdr("3. structured listings (JSON) that could replace the crawl")
for u in (f"{BASE}/query/rest/getChildren/{SD}?depth=-1&media=json",
          f"{BASE}/xwiki/query/rest/getChildren/{SD}?depth=1&media=json",
          f"{BASE}/bin/query/rest/getChildren/{SD}?depth=1&media=json",
          f"{BASE}/query/rest/getLastModified/{SD}.*?media=json",
          f"{BASE}/query/rest/searchDocs/{SD}?number=5&media=json",
          f"{BASE}/rest/suggest?word=itsm263&type=pages"):
    probe(u.replace(BASE, ""), u)
probe("search UI json", f"{BASE}/bin/search/main/?query=%22BMC%20Helix%20ITSM%22&outputSyntax=plain")
probe("livetable json",
      f"{BASE}/bin/view/{S}/WebHome?localePreference=en&xpage=livetable&outputSyntax=plain")

hdr("4. how many links does ONE section page expose? (nav completeness)")
for page in (SEC, f"{SEC}/Product-overview", "Administering"):
    r = S2.get(f"{BASE}/bin/{S}/{page}/", timeout=90)
    b = r.text
    links = set(re.findall(r"/bin/(?:view/)?" + re.escape(S) + r"/([A-Za-z0-9._/-]+)/", b))
    innav = re.findall(r'class="[^"]*(?:active|current|child)[^"]*"[^>]*href="([^"]+)"', b)
    print(f"- {page}: `{r.status_code}` bytes={len(b)} uniq-in-space-links={len(links)} "
          f"nav-marked={len(innav)}")
    print(f"    sample: {sorted(links)[:5]}")
    sib = [l for l in links if l.count("/") >= 1]
    print(f"    deeper-than-section links: {len(sib)}")

hdr("5. is there an async/lazy nav fragment per page?")
for u in (f"{BASE}/bin/get/{S}/{SEC}/WebHome?outputSyntax=plain&sheet=HelixNavigation.HelixDocNavigationUIX",
          f"{BASE}/bin/get/{S}/{SEC}/WebHome?outputSyntax=plain&sheet=XWiki/BMC/CETS/Macros/Navigation/BMCPageNavMacro",
          f"{BASE}/bin/jsx/XWiki/BMC/CETS/Macros/Navigation/BmcPageTreeMacro?language=en&docVersion=13.1"):
    probe(u.replace(BASE, ""), u)
print("\nPROBE-END")
PY
