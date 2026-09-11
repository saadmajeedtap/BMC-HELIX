"""Authoritative page inventory for a documentation space.

BMC's own "Export > PDF" modal lazily renders the page tree through
``XWiki.ExportDocumentTree``; that endpoint is the same source of truth the
website uses to decide which pages belong to a space, so we walk it and get an
exact inventory instead of guessing from a crawl. Every node is expanded once,
which also proves no page is silently skipped.
"""
from __future__ import annotations

import json
import os
import re
import time

from bs4 import BeautifulSoup

from .config import (BASE, is_denied, norm_doc, pretty_url, safe_name, url_to_doc)


def fragment_url(space_path: str, root_doc: str, limit: int = 500,
                 sheet: str = "XWiki.ExportDocumentTree") -> str:
    return (f"{BASE}/bin/get/{space_path}/WebHome?outputSyntax=plain"
            f"&sheet={sheet}&filterHiddenDocuments=false&showTranslations=false"
            f"&limit={limit}&root=document%3A{root_doc}")


def parse_fragment(html: str, space_path: str, space_dot_name: str):
    """Return [{title, doc, closed}] for one tree fragment. Tolerates markup drift."""
    out = []
    if not html:
        return out
    soup = BeautifulSoup(html, "lxml")
    for li in soup.select("li"):
        a = li.find("a", href=True)
        if not a:
            continue
        title = a.get_text(" ", strip=True) or ""
        doc = a.get("data-document") or a.get("data-id") or a.get("data-node") or ""
        if not doc:
            doc = url_to_doc(a["href"], space_path, space_dot_name) or ""
        if not doc:
            continue
        if doc.startswith("document:"):
            doc = doc.split(":", 1)[1]
        cls = " ".join(li.get("class") or []) + " " + " ".join(a.get("class") or [])
        closed = ("closed" in cls) or ("jstree-closed" in cls)
        expanded = li.find("ul") is not None
        out.append({"title": title, "doc": norm_doc(f"{space_dot_name}.{doc}")
                    if not doc.startswith(space_dot_name) else norm_doc(doc),
                    "closed": closed and not expanded})
    if out:
        return out
    # Fallback: sweep raw hrefs (fragment not li-based, or attrs unknown).
    pat = re.compile(r'href="([^"]*(?:/bin/(?:view/)?)?' + re.escape(space_path) + r'/([^"]+?)/?"')
    seen = set()
    for _href, tail in pat.findall(html):
        doc = norm_doc(f"{space_dot_name}." + tail.strip("/").replace("/", "."))
        if doc in seen or not doc:
            continue
        seen.add(doc)
        out.append({"title": doc.rsplit(".", 1)[-1], "doc": doc, "closed": True})
    return out


class Inventory:
    """Ordered, hierarchically-linked page inventory."""

    def __init__(self, space_path: str):
        self.space_path = space_path
        self.space_dot = space_path.replace("/", ".")
        self.nodes = {}          # doc -> node dict
        self.denied = []         # filtered-out authoring artifacts (auditable)
        self.expand_failures = []

    # ------------------------------------------------------------------- adding
    def add(self, doc, title, parent=None, depth=1, closed=None):
        doc = norm_doc(doc)
        if not doc or doc == self.space_dot:
            return None
        if is_denied(doc):
            if doc not in [d for d in self.denied]:
                self.denied.append(doc)
            return None
        n = self.nodes.get(doc)
        if n is None:
            n = {
                "doc": doc,
                "title": title or doc.rsplit(".", 1)[-1],
                "parent": parent,
                "depth": depth,
                "children": [],
                "closed": closed,
                "url": pretty_url(doc, self.space_path, self.space_dot),
                "slug": safe_name(doc),
            }
            self.nodes[doc] = n
        else:
            if title and (n["title"] == n["doc"].rsplit(".", 1)[-1] or len(title) > len(n["title"])):
                n["title"] = title
            if parent and not n["parent"]:
                n["parent"] = parent
            if closed is not None:
                n["closed"] = closed
        return n

    def child_docs(self, doc):
        return self.nodes[doc]["children"] if doc in self.nodes else []

    # ---------------------------------------------------------------- traversal
    def roots(self):
        return [d for d, n in self.nodes.items() if not n["parent"] or n["parent"] not in self.nodes]

    def walk(self):
        """Depth-first in navigation order; returns every doc exactly once."""
        order, seen = [], set()

        def go(doc):
            if doc in seen or doc not in self.nodes:
                return
            seen.add(doc)
            order.append(doc)
            for c in self.nodes[doc]["children"]:
                go(c)
        for r in self.roots():
            go(r)
        for d in self.nodes:  # any orphan not reachable from a root
            go(d)
        return order

    # ------------------------------------------------------------------ numbers
    def stats(self):
        dd = {}
        for n in self.nodes.values():
            dd[n["depth"]] = dd.get(n["depth"], 0) + 1
        return {"pages": len(self.nodes), "denied_filtered": len(self.denied),
                "expand_failures": len(self.expand_failures),
                "depth_histogram": dd, "roots": len(self.roots())}

    def save(self, path):
        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
        json.dump({"space_path": self.space_path, "stats": self.stats(),
                   "denied": self.denied, "expand_failures": self.expand_failures,
                   "order": self.walk(), "nodes": self.nodes},
                  open(path, "w"), indent=1)

    @classmethod
    def load(cls, path):
        d = json.load(open(path))
        inv = cls(d["space_path"])
        inv.nodes = d["nodes"]
        inv.denied = d.get("denied", [])
        inv.expand_failures = d.get("expand_failures", [])
        return inv


def build_inventory(http, space_path: str, max_rounds=40, limit=500, time_budget=None,
                    verbose=True):
    """Recursively expand the export document tree from the space root."""
    inv = Inventory(space_path)
    t0 = time.time()
    root = f"{inv.space_dot}.WebHome"
    r = http.get(fragment_url(space_path, root, limit))
    if r is None or r[0] != 200:
        raise RuntimeError(f"document tree endpoint unreachable for {space_path}: {r}")
    top = parse_fragment(r[1], space_path, inv.space_dot)
    if not top:
        raise RuntimeError("document tree fragment parsed 0 children; "
                           "check parse_fragment() against the live markup")
    for c in top:
        inv.add(c["doc"], c["title"], parent=norm_doc(inv.space_dot), depth=1,
                closed=c["closed"])
    if verbose:
        print(f"[tree] top level: {len(top)} sections", flush=True)

    frontier = [norm_doc(i) for i in inv.nodes if inv.nodes[i]["closed"] is not False]
    rounds = 0
    while frontier and rounds < max_rounds:
        rounds += 1
        if time_budget and time.time() - t0 > time_budget:
            if verbose:
                print(f"[tree] time budget reached, {len(frontier)} nodes left unexpanded",
                      flush=True)
            break
        todo = [d for d in dict.fromkeys(frontier)
                if d in inv.nodes and not inv.nodes[d].get("_expanded")]
        if not todo:
            break
        urls = {d: fragment_url(space_path, f"{d}.WebHome", limit) for d in todo}
        res = http.get_many(list(urls.values()))
        nxt = []
        for d in todo:
            inv.nodes[d]["_expanded"] = True
            key = urls[d]
            r = res.get(key)
            if r is None:
                inv.expand_failures.append(d)
                continue
            kids = parse_fragment(r[1], space_path, inv.space_dot)
            inv.nodes[d]["children"] = []
            for c in kids:
                n = inv.add(c["doc"], c["title"], parent=d,
                            depth=inv.nodes[d]["depth"] + 1, closed=c["closed"])
                if n is None:
                    continue
                if c["doc"] == d:
                    continue
                inv.nodes[d]["children"].append(n["doc"])
                if c["doc"] in inv.nodes and not inv.nodes[c["doc"]].get("_expanded"):
                    nxt.append(c["doc"])
        frontier = nxt
        if verbose:
            print(f"[tree] round {rounds}: expanded={len(todo)} queued={len(nxt)} "
                  f"total={len(inv.nodes)} t={time.time()-t0:.0f}s", flush=True)
    for d in inv.nodes:
        inv.nodes[d].pop("_expanded", None)
    return inv
