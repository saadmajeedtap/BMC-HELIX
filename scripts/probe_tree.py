#!/usr/bin/env python3
"""Probe the XWiki document-tree API used by BMC's own export modal.

Goal: an authoritative, complete inventory of every page under the
BMC Helix ITSM 26.3 space so the PDF build can prove 100% coverage.
Writes /tmp/w/inventory.json and prints a markdown report.
"""
import json
import os
import re
import sys
import time
from concurrent.futures import ThreadPoolExecutor

import requests
from bs4 import BeautifulSoup

BASE = "https://docs.helixops.ai"
SPACE_PATH = "Service-Management/IT-Service-Management/BMC-Helix-ITSM/itsm263"
SPACE_DOT = SPACE_PATH.replace("/", ".")
UA = ("Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/126.0 Safari/537.36")
W = "/tmp/w"
os.makedirs(W, exist_ok=True)

S = requests.Session()
S.headers["User-Agent"] = UA

EXCL = ""  # no exclusions: we want the full space


def tree_url(root_doc, limit=500):
    """URL of the lazy tree endpoint for one node (same one the export modal uses)."""
    return (f"{BASE}/bin/get/{SPACE_PATH}/WebHome?outputSyntax=plain"
            f"&sheet=XWiki.ExportDocumentTree&filterHiddenDocuments=false"
            f"&showTranslations=false&limit={limit}"
            f"&root=document%3A{root_doc}")


def get(url, tries=4):
    for i in range(tries):
        try:
            r = S.get(url, timeout=60)
            if r.status_code == 200:
                return r.text
            if r.status_code in (429, 503):
                time.sleep(3 * (i + 1))
                continue
            return None
        except Exception:
            time.sleep(2 * (i + 1))
    return None


def parse_children(html):
    """Return [(title, docRef, hasChildren, href)] from a tree fragment.

    The XWiki tree widget renders <li class="closed"><a data-document="Space.Page"
    href="/bin/view/...">Title</a></li> lazily; older builds use data-id / plain
    hrefs. Handle all of them, and fall back to a regex sweep of the fragment.
    """
    if not html:
        return []
    out = []
    soup = BeautifulSoup(html, "lxml")
    lis = soup.select("li")
    for li in lis:
        a = li.find("a", href=True)
        if not a:
            continue
        doc = a.get("data-document") or a.get("data-id") or a.get("data-node") or ""
        href = a.get("href") or ""
        cls = " ".join(li.get("class") or [])
        has = "closed" in cls or "jstree-closed" in cls or (
            li.find("ul", recursive=False) is None and "open" not in cls and li.has_attr("data-has-children"))
        if li.find("a") is not a:
            pass
        title = a.get_text(strip=True)
        if not doc:
            m = re.search(r"/bin/(?:view|get|edit)/" + re.escape(SPACE_PATH) + r"/([A-Za-z0-9._/-]+)/?", href)
            if m:
                doc = SPACE_DOT + "." + m.group(1).strip("/").replace("/", ".")
        if not doc:
            continue
        out.append((title, doc, bool(has), href))
    if not out:  # fragment not <li>-based: sweep for document refs
        for doc in re.findall(r'data-document="([^"]+)"', html):
            out.append((doc.rsplit(".", 1)[-1], doc, False, ""))
    # de-dup, keep first
    seen = set()
    res = []
    for t in out:
        if t[1] in seen:
            continue
        seen.add(t[1])
        res.append(t)
    return res


def main():
    rep = []
    rep.append("# document-tree probe")
    t0 = time.time()

    raw = get(tree_url(f"{SPACE_DOT}.WebHome", limit=500))
    rep.append(f"- root fragment: bytes={len(raw) if raw else 0} in {time.time()-t0:.1f}s")
    rep.append("```")
    rep.append((raw or "")[:2000])
    rep.append("```")

    kids = parse_children(raw)
    rep.append(f"- top-level children parsed: {len(kids)}")
    for t in kids[:14]:
        rep.append(f"  - {t[0]!r} doc={t[1][:90]!r} closed={t[2]}")

    # dump one section fragment so the markup shape is visible for the real builder
    if kids:
        sec = kids[1][1] if len(kids) > 1 else kids[0][1]
        frag = get(tree_url(sec, limit=500))
        rep.append(f"- section fragment for {sec!r} bytes={len(frag) if frag else 0}")
        rep.append("```")
        rep.append((frag or "")[:1500])
        rep.append("```")
        rep.append(f"  - parsed children of that section: {len(parse_children(frag))}")

    # full recursive expansion
    inventory = {}
    errors = []

    def expand(doc):
        html = get(tree_url(doc, limit=500))
        ch = parse_children(html)
        return doc, [(c[0], c[1], c[2], c[3]) for c in ch], html

    roots = [(k[1] or f"{SPACE_DOT}.WebHome", k[0]) for k in kids] or [(f"{SPACE_DOT}.WebHome", "WebHome")]
    frontier = list(roots)
    depth = {d: 1 for d, _ in roots}
    for d, n in roots:
        inventory[d] = {"title": n, "parent": f"{SPACE_DOT}.WebHome", "depth": 1, "children": []}
    seen = set()
    rounds = 0
    with ThreadPoolExecutor(max_workers=4) as ex:
        while frontier and rounds < 40:
            rounds += 1
            todo = [d for d in frontier if d not in seen]
            seen.update(todo)
            if not todo:
                break
            res = list(ex.map(expand, todo))
            nxt = []
            for doc, ch, html in res:
                if html is None:
                    errors.append(doc)
                inventory.setdefault(doc, {"title": doc.split(".")[-1], "children": []})
                inventory[doc]["children"] = [c[1] for c in ch]
                for title, cd, closed, href in ch:
                    if cd not in inventory:
                        depth[cd] = depth.get(doc, 1) + 1
                        inventory[cd] = {"title": title, "parent": doc,
                                         "depth": depth[cd], "children": [], "href": href}
                    if closed or (href and href.rstrip("/").endswith(cd.split(".")[-1])):
                        nxt.append(cd)
            frontier = list(dict.fromkeys(nxt))
            rep.append(f"  round {rounds}: expanded={len(todo)} next={len(frontier)} "
                       f"total={len(inventory)} t={time.time()-t0:.0f}s")
            if time.time() - t0 > 1200:
                rep.append("  (stopped early: probe time budget)")
                break

    rep.append(f"- TOTAL PAGES DISCOVERED: {len(inventory)} in {time.time()-t0:.0f}s")
    rep.append(f"- errors: {len(errors)} {errors[:5]}")
    dd = {}
    for v in inventory.values():
        dd[v.get("depth", 0)] = dd.get(v.get("depth", 0), 0) + 1
    rep.append(f"- depth histogram: {json.dumps(dd)}")
    leaves = sum(1 for v in inventory.values() if not v.get("children"))
    rep.append(f"- leaves: {leaves}, branches: {len(inventory)-leaves}")

    # sample leaf page size to estimate crawl volume
    sample = [d for d, v in inventory.items() if not v.get("children")][:12]
    sizes = []
    for doc in sample:
        path = doc.replace(SPACE_DOT + ".", "").replace(".", "/")
        r = S.get(f"{BASE}/bin/{SPACE_PATH}/{path}/", timeout=60)
        if r.status_code == 200:
            sizes.append(len(r.content))
        else:
            sizes.append(-1)
    if sizes:
        avg = sum(s for s in sizes if s > 0) / max(1, len([s for s in sizes if s > 0]))
        rep.append(f"- leaf page html bytes: avg={avg:.0f} -> est. total html="
                   f"{avg*len(inventory)/1e6:.0f} MB")
    json.dump(inventory, open(f"{W}/inventory.json", "w"), indent=1)
    rep.append(f"- inventory written: {W}/inventory.json ({os.path.getsize(W+'/inventory.json')} bytes)")
    print("\n".join(rep))


if __name__ == "__main__":
    sys.setrecursionlimit(10000)
    main()
