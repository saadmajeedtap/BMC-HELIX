#!/usr/bin/env python3
"""Probe v2: find the space-tree endpoint the site itself uses, verbatim.

For every page we scrape `data-url` / tree-ish hrefs, then request those URLs
EXACTLY as the site wrote them (only `limit` bumped), under a few header
combinations. The winning raw body is saved so the real HTML can be parsed
against a real fixture instead of a guess.
"""
import json
import os
import re
import sys
import requests

BASE = os.environ.get("HELIX_BASE_URL", "https://docs.helixops.ai")
SPACE = os.environ.get("SPACE_PATH",
                       "Service-Management/IT-Service-Management/BMC-Helix-ITSM/itsm263")
OUT = os.environ.get("PROBE_OUT", ".")
os.makedirs(OUT, exist_ok=True)
UA = {"User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124 Safari/537.36"}

s = requests.Session()
s.headers.update(UA)
log = print


def get(url, extra=None, timeout=60):
    h = dict(UA)
    if extra:
        h.update(extra)
    try:
        r = s.get(url, headers=h, timeout=timeout, allow_redirects=True)
        return r.status_code, r.text, dict(r.headers)
    except Exception as e:            # noqa: BLE001
        return None, f"EXC {e!r}", {}


tree_urls = set()
pages = [f"{BASE}/bin/{SPACE}/", f"{BASE}/bin/view/{SPACE}/WebHome",
         f"{BASE}/bin/{SPACE}/Getting-started/WebHome/"]
ref_for = {}
log("== pages scraped for tree endpoints ==")
for p in pages:
    st, body, _ = get(p)
    log(f"- {p} -> {st} bytes={len(body)}")
    if st != 200:
        continue
    ref_for[p] = body
    html = body.replace("&#38;", "&").replace("&amp;", "&")
    for m in re.findall(r'/bin/[a-z]+/[^"\'\s]*Tree[^"\'\s]*', html):
        tree_urls.add(m)
    for m in re.findall(r'data-url="([^"]+)"', html):
        if "Tree" in m or "tree" in m:
            tree_urls.add(m.replace("&amp;", "&"))
    for m in re.findall(r'data-(?:reference|root-page|treenavigation)[^ >]*', html)[:6]:
        log(f"    attr: {m[:150]}")
log(f"== {len(tree_urls)} tree-ish endpoints discovered ==")

variants = []
for u in sorted(tree_urls):
    absu = u if u.startswith("http") else BASE + u
    variants.append(("verbatim", absu))
    if "limit=" in absu:
        variants.append(("limit=5000", re.sub(r"limit=\d+", "limit=5000", absu)))
    variants.append(("no-exclusions", re.sub(r"&?exclusions=[^&]*", "", absu)))
    variants.append(("limit5000+noexcl",
                     re.sub(r"&?exclusions=[^&]*", "",
                            re.sub(r"limit=\d+", "limit=5000", absu))))

HEADERS = [
    ("plain", {}),
    ("xhr", {"X-Requested-With": " XMLHttpRequest"}),
    ("xhr+ref", {"X-Requested-With": "XMLHttpRequest",
                 "Referer": pages[0], "Accept": "text/html,*/*"}),
]

log("\n== endpoint x header matrix ==")
winner = None
for lbl, url in variants:
    for hlbl, hh in HEADERS:
        u = url if "xmlhttprequest" not in url else url
        st, body, hd = get(u, hh)
        n_a = len(re.findall(r"<a\b", body or ""))
        n_li = len(re.findall(r"<li\b", body or ""))
        log(f"- [{lbl}|{hlbl}] {st} bytes={len(body or '')} a={n_a} li={n_li} "
            f"ct={hd.get('Content-Type','')}\n    {u[:190]}")
        if st == 200 and (n_a or n_li) and body and "contentTitle" not in body[:4000]:
            if winner is None or len(body) > winner[2]:
                winner = (u, body, len(body), hd)
    if winner and "verbatim" in lbl:
        break

log("\n== winner raw body (first 2200 chars) ==")
if winner:
    u, body = winner[0], winner[1]
    log(f"url: {u}")
    log("```")
    log(body[:2200])
    log("```")
    with open(os.path.join(OUT, "tree-fragment.html"), "w", encoding="utf-8") as f:
        f.write(body)
    log(f"saved raw fragment: tree-fragment.html ({len(body)} bytes)")
    anchors = re.findall(r'<a\b[^>]*href="[^"]*"[^>]*>.*?</a>', body, re.S)[:6]
    log("== first anchors ==")
    for a in anchors:
        log("    " + re.sub(r"\s+", " ", a)[:220])
else:
    log("NO endpoint returned a navigable fragment; BFS fallback must be used")

log("\n== classic XWiki DocumentTree shapes ==")
sd = SPACE.replace("/", ".")
for q in (f"outputSyntax=plain&tree=1&root={sd}.WebHome",
          f"outputSyntax=plain&tree=1&data={sd}.WebHome",
          f"sheet=XWiki.DocumentTree&outputSyntax=plain&root=document%3Axwiki%3A{sd}.WebHome",
          "xpage=rdf", "outputSyntax=plain&xpage=rdf"):
    for base_u in (f"{BASE}/bin/get/{SPACE}/WebHome", f"{BASE}/bin/get/{SPACE}/WebHome/",
                   f"{BASE}/bin/get/{SPACE}/Getting-started/WebHome"):
        url = f"{base_u}?{q}"
        st, body, hd = get(url)
        n_a = len(re.findall(r"<a\b", body or ""))
        if st == 200 and n_a:
            log(f"- {url[:170]}\n    200 bytes={len(body)} a={n_a} ct={hd.get('Content-Type')}")
            if "rdf:about" in (body or ""):
                log("    RDF! first items:")
                for m in re.findall(r"<li><a href='([^']+)'>", body)[:5]:
                    log(f"      {m}")
                with open(os.path.join(OUT, "tree-rdf.xml"), "w", encoding="utf-8") as f:
                    f.write(body)
        else:
            log(f"- {url[:170]} -> {st} a={n_a}")

log("\n== how complete is BFS? (link-closure from a section page) ==")
sd_pat = re.escape(f"{BASE}/bin/") + r".*?" + re.escape(SPACE)
st, body, _ = get(pages[0])
if st == 200:
    links = set(re.findall(r'href="(' + sd_pat + r')["\']', body))
    log(f"- landing page exposes {len(links)} in-space links")
log("PROBE-END")
