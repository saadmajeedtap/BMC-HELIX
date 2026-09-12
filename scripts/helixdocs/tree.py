"""Authoritative page inventory for a documentation space.

Primary source: the portal's own lazy document-tree endpoint - the same one its
"Export > PDF" dialog uses to list the pages of a space. Because that endpoint is
what the website itself trusts, walking it to exhaustion gives an exact inventory
(and therefore an honest completeness claim) instead of a crawl-and-hope.

The endpoint URL is *scraped from the live pages* and several shapes are tried, so
the tool keeps working when BMC upgrades the portal. If no tree endpoint answers,
we fall back to link-closure enumeration and say so loudly in the report.
"""
from __future__ import annotations

import json
import os
import re
import time

from bs4 import BeautifulSoup

from .config import (BASE, is_denied, norm_doc, pretty_url, safe_name, url_to_doc)

ATTR_DOC_HINTS = ("data-document", "data-reference", "data-id", "data-node",
                  "data-entityref", "data-xwiki-reference")

FALLBACK_TEMPLATES = [
    "{base}/bin/get/{space}/WebHome/?outputSyntax=plain&sheet=XWiki.ExportDocumentTree"
    "&filterHiddenDocuments=false&showTranslations=false&limit={limit}"
    "&root=document%3Axwiki%3A{root}",
    "{base}/bin/get/{space}/WebHome?outputSyntax=plain&sheet=XWiki.ExportDocumentTree"
    "&filterHiddenDocuments=false&showTranslations=false&limit={limit}"
    "&root=document%3Axwiki%3A{root}",
    "{base}/bin/get/XWiki/BMC/CETS/Macros/Navigation/BmcDocumentTree"
    "?limit={limit}&outputSyntax=plain&root=document%3Axwiki%3A{root}",
    "{base}/bin/get/XWiki/BMC/CETS/Macros/Navigation/BmcDocumentTree"
    "?limit={limit}&outputSyntax=plain&root=document%3A{root}",
    "{base}/bin/get/{space}/WebHome/?outputSyntax=plain&sheet=XWiki.PageTree"
    "&limit={limit}&root=document%3Axwiki%3A{root}",
]


def _looks_like_doc(val: str, space_dot: str) -> bool:
    return bool(val) and space_dot in val and not val.startswith(("http", "/", "#"))


class TreeSource:
    def __init__(self, http, space_path, limit=500, verbose=True):
        self.http = http
        self.space_path = space_path
        self.space_dot = space_path.replace("/", ".")
        self.limit = limit
        self.verbose = verbose
        self.template = None
        self.notes = []

    # ------------------------------------------------------------- url plumbing
    def url(self, tmpl, root_doc):
        try:
            return tmpl.format(base=BASE, space=self.space_path, limit=self.limit,
                               root=root_doc)
        except Exception:
            return None

    def scrape_templates(self, html):
        out = []
        html = (html or "").replace("&#38;", "&").replace("&amp;", "&")
        for pat in (r"/bin/get/[^ \t\r\n\"'<>]*DocumentTree[^ \t\r\n\"'<>]*",
                    r"/bin/get/[^ \t\r\n\"'<>]*PageTree[^ \t\r\n\"'<>]*"):
            for m in re.finditer(pat, html):
                u = m.group(0)
                u = re.sub(r"[?&]root=[^&#]*", "", u)
                u = re.sub(r"[?&]limit=[^&#]*", "", u)
                u = re.sub(r"[?&]+$", "", u).replace("&&", "&").replace("?&", "?")
                sep = "&" if "?" in u else "?"
                u = f"{u}{sep}limit={{limit}}&root=document%3Axwiki%3A{{root}}"
                if not u.startswith("http"):
                    u = BASE + u
                u = u.replace(BASE, "{base}")
                u = u.replace(f"/bin/get/{self.space_path}/WebHome", "/bin/get/{space}/WebHome")
                if u not in out and "{root}" in u:
                    out.append(u)
        return out

    # ------------------------------------------------------------------ parsing
    def parse_fragment(self, raw):
        """-> [{title, doc, closed}] from a fragment (HTML or JSON)."""
        res = []
        if not raw:
            return res
        s = raw.strip()
        if s[:1] in "[{":
            try:
                data = json.loads(s)
            except Exception:
                data = None
            if data is not None:
                def walk(obj):
                    items = obj if isinstance(obj, list) else obj.get("children") or [] \
                        if isinstance(obj, dict) else []
                    for it in items:
                        if not isinstance(it, dict):
                            continue
                        doc = ""
                        for k in ("reference", "document", "id", "data", "entity", "path"):
                            v = it.get(k)
                            if isinstance(v, str) and _looks_like_doc(v, self.space_dot):
                                doc = v
                        title = it.get("label") or it.get("name") or it.get("title") or ""
                        kids = it.get("children")
                        res.append({"title": str(title), "doc": norm_doc(doc),
                                    "closed": bool(kids is None and it.get("hasChildren"))})
                        if isinstance(kids, list):
                            walk(kids)
                walk(data)
                if res:
                    return res
        soup = BeautifulSoup(raw, "lxml")
        for li in soup.select("li"):
            a = li.find("a", href=True)
            if a is None:
                continue
            doc = ""
            for el in (a, li):
                for k in ATTR_DOC_HINTS:
                    v = el.get(k) or ""
                    if _looks_like_doc(v, self.space_dot):
                        doc = v.replace("document:", "").replace("xwiki:", "")
                        break
                if doc:
                    break
            if not doc:
                m = re.search(r"/bin/(?:view|get|edit|inline)/" +
                              re.escape(self.space_path) + r"/([A-Za-z0-9._/-]+)",
                              a["href"])
                if m:
                    doc = self.space_dot + "." + m.group(1).strip("/").replace("/", ".")
            if not doc:
                continue
            cls = " ".join((li.get("class") or [])) + " " + " ".join((a.get("class") or []))
            closed = ("closed" in cls) or ("jstree-closed" in cls) or \
                (str(li.get("data-haschildren", "")).lower() == "true" and not li.find("ul"))
            if li.find("ul") is not None:
                closed = False
            title = re.sub(r"\s+", " ", a.get_text(" ", strip=True)) or ""
            res.append({"title": title, "doc": norm_doc(doc), "closed": closed})
        if not res:  # last resort: sweep hrefs into the space
            for href in re.findall(r'href="([^"]+' + re.escape(self.space_path) + r'/[^"]+)"', raw):
                d = url_to_doc(href, self.space_path, self.space_dot)
                if d:
                    res.append({"title": d.rsplit(".", 1)[-1], "doc": d, "closed": True})
        seen, out = set(), []
        for r in res:
            if not r["doc"] or r["doc"] in seen or r["doc"] == self.space_dot:
                continue
            if r["doc"].startswith("document:"):
                r["doc"] = norm_doc(r["doc"].split(":", 1)[-1])
            seen.add(r["doc"])
            out.append(r)
        return out

    # -------------------------------------------------------------------- probe
    def probe(self, page_html=""):
        """Pick the first template that returns a parseable, non-empty fragment."""
        templates = self.scrape_templates(page_html) + FALLBACK_TEMPLATES
        self.notes = []
        root = f"{self.space_dot}.WebHome"
        samples = []
        for tmpl in templates:
            u = self.url(tmpl, root)
            if not u:
                continue
            r = self.http.get(u)
            if r is None:
                self.notes.append(f"no-response {u[:120]}")
                continue
            status, body, ctype = r
            kids = self.parse_fragment(body)
            samples.append({"url": u, "status": status, "bytes": len(body or ""),
                            "children": len(kids),
                            "sample": re.sub(r"\s+", " ", (body or ""))[:900]})
            if status == 200 and len(kids) >= 1:
                self.template = tmpl
                self.notes.append(f"USING {tmpl[:150]} -> {len(kids)} children")
                self.samples = samples
                if self.verbose:
                    print(f"[tree] endpoint OK ({len(kids)} top-level children)", flush=True)
                return kids
            self.notes.append(f"http={status} children={len(kids)} {u[:110]}")
        self.samples = samples
        return None

    def _root_candidates(self, doc):
        return [f"{doc}.WebHome", doc] if doc != self.space_dot else [f"{doc}.WebHome"]

    def children(self, doc):
        for root in self._root_candidates(doc):
            u = self.url(self.template, root)
            r = self.http.get(u)
            if r is not None and r[0] == 200:
                return self.parse_fragment(r[1])
        return None

    def children_many(self, docs):
        """Expand many nodes at once (rounds are I/O bound). {doc: [children]|None}."""
        first = {d: self.url(self.template, f"{d}.WebHome" if d != self.space_dot
                             else f"{d}.WebHome") for d in docs}
        res = self.http.get_many(list(first.values()))
        out, retry = {}, []
        for d, u in first.items():
            r = res.get(u)
            if r is not None and r[0] == 200:
                out[d] = self.parse_fragment(r[1])
            else:
                retry.append(d)
        for d in retry:                      # leaf sections often have no WebHome doc
            if d == self.space_dot:
                out[d] = None
                continue
            u = self.url(self.template, d)
            r = self.http.get(u)
            out[d] = self.parse_fragment(r[1]) if (r is not None and r[0] == 200) else None
        return out


class Inventory:
    """Ordered, hierarchically-linked page inventory."""

    def __init__(self, space_path: str, method: str = "export-tree"):
        self.space_path = space_path
        self.space_dot = space_path.replace("/", ".")
        self.nodes = {}
        self.denied = []
        self.expand_failures = []
        self.method = method
        self.root_doc = self.space_dot + ".WebHome"

    def add(self, doc, title, parent=None, depth=1, closed=None):
        doc = norm_doc(doc) if doc != self.space_dot else doc
        if not doc or doc == self.space_dot + ".WebHome":
            return None
        if is_denied(doc):
            if doc not in self.denied:
                self.denied.append(doc)
            return None
        n = self.nodes.get(doc)
        if n is None:
            n = {"doc": doc, "title": title or doc.rsplit(".", 1)[-1], "parent": parent,
                 "depth": depth, "children": [], "closed": closed,
                 "url": pretty_url(doc, self.space_path, self.space_dot),
                 "slug": safe_name(doc)}
            self.nodes[doc] = n
        else:
            if title and len(title) > len(n["title"] or ""):
                n["title"] = title
            if parent and not n["parent"]:
                n["parent"] = parent
            if closed is not None:
                n["closed"] = closed
        return n

    def ensure_root(self, title=""):
        """The space's own landing page is part of the documentation - keep it."""
        root = self.space_dot
        if root not in self.nodes:
            self.nodes[root] = {"doc": root, "title": title or "Home", "parent": None,
                               "depth": 1, "children": [], "closed": False,
                               "url": pretty_url(root, self.space_path, self.space_dot),
                               "slug": safe_name(root) or "space-home", "is_space_root": True}
        for d, n in self.nodes.items():
            if d == root:
                continue
            if n.get("parent") in (self.root_doc, None) or n["parent"] not in self.nodes:
                n["parent"] = root
                n["depth"] = 2 if n.get("depth", 1) <= 1 else n["depth"] + 1
        self.nodes[root]["children"] = [d for d, n in self.nodes.items()
                                       if n.get("parent") == root]
        return root

    def roots(self):
        return [d for d, n in self.nodes.items()
                if not n.get("parent") or n["parent"] not in self.nodes]

    def children(self, doc):
        """Ordered children of doc; unreached nodes hang off the space root so the
        build order always starts at the portal landing page and never drops a page."""
        n = self.nodes.get(doc)
        if n is None:
            return []
        kids = [c for c in n.get("children", []) if c in self.nodes and c != doc]
        if doc == self.space_dot:
            linked = {c for v in self.nodes.values() for c in (v.get("children") or [])}
            ancestors = set()
            for v in self.nodes.values():
                ancestors.add(v.get("parent"))
            kids += [d for d in self.nodes
                     if d != doc and d not in linked and d not in kids
                     and (d not in ancestors or not self.nodes[d].get("parent"))]
        return kids

    def walk(self):
        order, seen = [], set()

        def go(doc, depth=0):
            if doc in seen or doc not in self.nodes or depth > 200:
                return
            seen.add(doc)
            order.append(doc)
            for c in self.children(doc):
                go(c, depth + 1)
        if self.space_dot in self.nodes:
            go(self.space_dot)
        for r in self.roots():
            go(r)
        for d in list(self.nodes):
            go(d)
        return order

    def stats(self):
        dd = {}
        for n in self.nodes.values():
            dd[n["depth"]] = dd.get(n["depth"], 0) + 1
        return {"method": self.method, "pages": len(self.nodes),
                "denied_filtered": len(self.denied),
                "expand_failures": len(self.expand_failures),
                "roots": len(self.roots()), "depth_histogram": dd}

    def save(self, path):
        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
        json.dump({"space_path": self.space_path, "method": self.method,
                   "stats": self.stats(), "denied": self.denied,
                   "expand_failures": self.expand_failures,
                   "order": self.walk(), "nodes": self.nodes},
                  open(path, "w"), indent=1)

    @classmethod
    def load(cls, path):
        d = json.load(open(path))
        inv = cls(d["space_path"], d.get("method", "export-tree"))
        inv.nodes, inv.denied = d["nodes"], d.get("denied", [])
        inv.expand_failures = d.get("expand_failures", [])
        return inv


def _section_matches(doc, title, wanted):
    if not wanted:
        return True
    last = (doc or "").rsplit(".", 1)[-1].lower()
    t = (title or "").lower().replace(" ", "-")
    return any(w in last or w in t or last in w for w in wanted)


def build_inventory(http, space_path, limit=500, max_rounds=60, time_budget=None,
                    verbose=True, diag_path="", only=None):
    """Expand the export document tree from the space root to exhaustion."""
    inv = Inventory(space_path, "export-tree")
    src = TreeSource(http, space_path, limit=limit, verbose=verbose)
    t0 = time.time()
    seed = http.get(f"{BASE}/bin/{space_path}/WebHome/")
    kids = src.probe(seed[1] if seed else "")
    if diag_path:
        json.dump({"notes": src.notes, "samples": getattr(src, "samples", [])[:6]},
                  open(diag_path, "w"), indent=1)
    if kids is None:
        raise RuntimeError("no document-tree endpoint returned children; see "
                           + (diag_path or "tree diagnostics"))
    wanted = {str(w).strip().lower().replace(" ", "-") for w in (only or []) if str(w).strip()}
    for c in kids:
        if wanted and not _section_matches(c["doc"], c["title"], wanted):
            inv.denied.append(c["doc"])      # out of scope for this run, but recorded
            continue
        inv.add(c["doc"], c["title"], parent=inv.root_doc, depth=1, closed=c["closed"])
    if wanted:
        if verbose:
            print(f"[tree] scoped to {len(inv.nodes)} of {len(kids)} top-level sections",
                  flush=True)
    inv.ensure_root()
    frontier = [d for d in inv.nodes if inv.nodes[d]["closed"] is not False]
    rounds = 0
    while frontier and rounds < max_rounds:
        rounds += 1
        if time_budget and time.time() - t0 > time_budget:
            inv.notes = [f"time budget hit with {len(frontier)} nodes queued"]
            break
        todo = [d for d in dict.fromkeys(frontier)
                if d in inv.nodes and not inv.nodes[d].get("_exp")]
        if not todo:
            break
        nxt = []
        got = src.children_many(todo)
        for d in todo:
            inv.nodes[d]["_exp"] = True
            ch = got.get(d)
            if ch is None:
                inv.expand_failures.append(d)
                continue
            inv.nodes[d]["children"] = []
            for c in ch:
                if c["doc"] == d:
                    continue
                n = inv.add(c["doc"], c["title"], parent=d,
                            depth=inv.nodes[d]["depth"] + 1, closed=c["closed"])
                if n is None:
                    continue
                if n["doc"] not in inv.nodes[n["doc"]]["children"]:
                    inv.nodes[d]["children"].append(n["doc"])
                if c["closed"] or n.get("closed"):
                    nxt.append(n["doc"])
        frontier = nxt
        if verbose:
            print(f"[tree] round {rounds}: expanded={len(todo)} queued={len(nxt)} "
                  f"total={len(inv.nodes)} t={time.time()-t0:.0f}s", flush=True)
    for d in list(inv.nodes):
        inv.nodes[d].pop("_exp", None)
    return inv


def bfs_inventory(http, space_path, seeds=None, max_pages=20000, time_budget=None,
                  verbose=True):
    """Fallback: discover pages by following every in-space link to a fixpoint."""
    inv = Inventory(space_path, "link-closure-fallback")
    t0 = time.time()
    start = seeds or [inv.root_doc]
    for d in start:
        inv.add(d, "Home", parent=None, depth=1, closed=True)
    frontier = list(inv.nodes)
    rounds = 0
    while frontier and rounds < 30 and len(inv.nodes) < max_pages:
        rounds += 1
        if time_budget and time.time() - t0 > time_budget:
            break
        urls = {d: inv.nodes[d]["url"] for d in frontier if d in inv.nodes}
        res = http.get_many(list(urls.values()))
        nxt = []
        for d, u in urls.items():
            r = res.get(u)
            inv.nodes[d]["_seen"] = True
            if r is None or r[0] != 200:
                inv.expand_failures.append(d)
                continue
            html = r[1]
            inv.nodes[d]["children"] = []
            m = re.search(r"/bin/(?:view/)?" + re.escape(space_path) + r"/([A-Za-z0-9._/-]+)/",
                          html)
            for href in set(re.findall(r'href="([^"]+' + re.escape(space_path) + r'[^"]*)"', html)):
                cd = url_to_doc(href, space_path, inv.space_dot)
                if not cd or cd == d:
                    continue
                n = inv.add(cd, cd.rsplit(".", 1)[-1].replace("-", " "), parent=d,
                            depth=inv.nodes[d]["depth"] + 1, closed=True)
                if n and n["doc"] not in inv.nodes[d]["children"]:
                    inv.nodes[d]["children"].append(n["doc"])
                    if not n.get("_seen"):
                        nxt.append(n["doc"])
        frontier = [x for x in dict.fromkeys(nxt) if not inv.nodes.get(x, {}).get("_seen")]
        if verbose:
            print(f"[tree:bfs] round {rounds}: +{len(nxt)} total={len(inv.nodes)} "
                  f"t={time.time()-t0:.0f}s", flush=True)
    for d in list(inv.nodes):
        inv.nodes[d].pop("_seen", None)
    return inv


# ------------------------------------------------------------------ navigation
# The portal exposes no usable anonymous listing API (every /bin/get/* form, and
# even the URL its own markup advertises, returns 404). What *is* authoritative is
# the navigation the page renders: the left tree shows the ancestors of the page
# plus their children, in menu order, with the real titles. Harvesting it from
# every page gives the complete menu tree -- and a page can only be in the menu
# of one of its ancestors, so the whole tree is covered by crawling all pages.
NAVISH = re.compile(r"(doc|main|left|side|global|page)?-?(nav|tree|toc|menu|contents?|sidebar)",
                    re.I)


def _doc_of(href, space_path, space_dot):
    return url_to_doc(href, space_path, space_dot)


def nav_container(soup, space_path):
    """The <ul> that carries the in-space navigation (the one with most in-space links)."""
    cands = list(soup.find_all("ul"))
    scored = []
    for ul in cands[:400]:
        chain = " ".join([(p.get("id") or "") + " " + " ".join(p.get("class") or [])
                          for p in list(ul.parents)[:4]])
        n = 0
        for a in ul.find_all("a", href=True):
            if space_path in a["href"]:
                n += 1
                if n > 200:
                    break
        if n:
            scored.append((n, 1 if NAVISH.search(chain or "") else 0, len(ul.get_text()), ul))
    if not scored:
        return None
    scored.sort(key=lambda t: (t[1], t[0]), reverse=True)
    return scored[0][3]


def nav_edges(soup, space_path, space_dot):
    """[(doc, parent, title, order)] from the nested <ul>/<li> structure."""
    root = nav_container(soup, space_path)
    if root is None:
        return []
    edges, ctr = [], [0]

    def walk(node, parent):
        for li in node.find_all("li", recursive=False):
            a = li.find("a", href=True)
            sub = li.find("ul", recursive=False)
            doc = _doc_of(a["href"], space_path, space_dot) if a is not None else None
            title = re.sub(r"\s+", " ", a.get_text(" ", strip=True)) if a is not None else ""
            if doc:
                ctr[0] += 1
                edges.append((doc, parent, title, ctr[0]))
            if sub is not None:
                walk(sub, doc or parent)
    walk(root, None)
    return edges


def _in_scope(doc, space_dot, wanted):
    """Is this document inside one of the requested top-level sections?"""
    if not wanted:
        return True
    rel = doc[len(space_dot) + 1:] if doc.startswith(space_dot + ".") else doc
    top = rel.split(".")[0].lower()
    return any(w == top or w in top or top in w for w in wanted)


def nav_inventory(http, space_path, max_pages=20000, time_budget=None, verbose=True,
                  only=None, batch=48):
    """Breadth-first over pages, taking structure from the rendered nav and
    completeness from every in-space link each page contains."""
    inv = Inventory(space_path, "rendered-navigation")
    sp, sd = inv.space_path, inv.space_dot
    wanted = {str(w).strip().lower().replace(" ", "-") for w in (only or []) if str(w).strip()}
    t0 = time.time()
    inv.add(sd, "Home", parent=None, depth=1, closed=False)
    inv.nodes[sd]["is_space_root"] = True
    visited, queue = set(), [sd]
    rounds = 0
    while queue and len(inv.nodes) < max_pages:
        rounds += 1
        if time_budget and time.time() - t0 > time_budget:
            inv.notes = [f"time budget hit, {len(queue)} pages still queued"]
            break
        todo = [d for d in dict.fromkeys(queue) if d not in visited and d in inv.nodes]
        if not todo:
            break
        # bounded rounds: keeps memory flat on a multi-thousand page space
        todo = todo[:max(8, batch)]
        urls = {d: inv.nodes[d]["url"] for d in todo}
        res = http.get_many(list(urls.values()))
        nxt = []
        for d, u in urls.items():
            visited.add(d)
            r = res.get(u)
            if r is None or r[0] != 200:
                inv.expand_failures.append(d)
                continue
            html = r[1]
            soup = BeautifulSoup(html, "lxml")
            # 1) structure: the menu this page renders
            for (cd, parent, title, order) in nav_edges(soup, sp, sd):
                if cd == d or is_denied(cd):
                    continue
                pd = parent if parent in inv.nodes else sd
                n = inv.add(cd, title or cd.rsplit(".", 1)[-1].replace("-", " "),
                             parent=pd, depth=inv.nodes[pd]["depth"] + 1, closed=False)
                if n is None:
                    continue
                n["nav_order"] = order
                if n.get("src") != "nav":
                    n["src"] = "nav"
                if cd not in inv.nodes[pd]["children"]:
                    inv.nodes[pd]["children"].append(cd)
                if wanted and not _in_scope(cd, sd, wanted):
                    # recorded so the report can be honest about it, never crawled
                    n["out_of_scope"] = True
                    if pd == sd and cd not in inv.denied:
                        inv.denied.append(cd)
                    continue
                if cd not in visited:
                    nxt.append(cd)
            # 2) completeness: anything else this page links to inside the space
            for href in re.findall(r'href="([^"]+' + re.escape(sp) + r'[^"]*)"', html):
                cd = _doc_of(href, sp, sd)
                if not cd or cd in visited or cd in inv.nodes:
                    continue
                a_txt = ""
                m = re.search(r'<a\b[^>]*href="' + re.escape(href) + r'"[^>]*>(.*?)</a>',
                              html, re.S)
                if m:
                    a_txt = re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", m.group(1))).strip()
                n = inv.add(cd, a_txt or cd.rsplit(".", 1)[-1].replace("-", " "),
                             parent=d, depth=inv.nodes[d]["depth"] + 1, closed=False)
                if n is None or n.get("out_of_scope"):
                    continue
                if wanted and not _in_scope(cd, sd, wanted):
                    n["out_of_scope"] = True
                    continue
                if n.get("src") is None:
                    n["src"] = "link"
                if cd not in inv.nodes[d]["children"]:
                    inv.nodes[d]["children"].append(cd)
                nxt.append(cd)
        queue = [x for x in dict.fromkeys(nxt) if x not in visited
                 and not inv.nodes.get(x, {}).get("out_of_scope")]
        if verbose:
            st = inv.stats()
            print(f"[nav] round {rounds}: visited={len(visited)} pages={st['pages']} "
                  f"queued={len(queue)} t={time.time()-t0:.0f}s", flush=True)
    # menu order wins; link-discovered children keep discovery order afterwards
    for n in inv.nodes.values():
        n["children"] = sorted(dict.fromkeys(n["children"]),
                               key=lambda c: (inv.nodes[c].get("nav_order") is None,
                                              inv.nodes[c].get("nav_order") or 0,
                                              inv.nodes[c]["title"].lower()))
    # Belt and braces: BMC names documents by their menu path
    # (``Administering.Configuring-logs`` is a child of ``Administering``), so a page
    # that the nav never showed us can still be hung on the right branch instead of
    # being flattened under whatever page happened to link to it first.
    for d, n in inv.nodes.items():
        if n.get("src") == "nav" or d == sd:
            continue
        parts = d.split(".")
        cand = None
        for i in range(len(parts) - 1, 1, -1):
            probe = ".".join(parts[:i])
            if probe in inv.nodes and probe != d:
                cand = probe
                break
        if cand and cand != n.get("parent"):
            old = n.get("parent")
            if old and old in inv.nodes and d in inv.nodes[old]["children"]:
                inv.nodes[old]["children"].remove(d)   # detach from the linking page
            n["parent"] = cand
            n["src"] = n.get("src") or "prefix"
            n["reparented_by_name"] = True
            if d not in inv.nodes[cand]["children"]:
                inv.nodes[cand]["children"].append(d)
    for d, n in inv.nodes.items():   # drop stale edges left by the re-parenting above
        n["children"] = [c for c in dict.fromkeys(n.get("children") or [])
                         if c in inv.nodes and c != d and inv.nodes[c].get("parent") == d]
    for d, n in inv.nodes.items():   # depths follow the final parent chain
        depth, cur, seen = 0, n.get("parent"), set()
        while cur and cur in inv.nodes and cur not in seen:
            seen.add(cur); depth += 1; cur = inv.nodes[cur].get("parent")
        n["depth"] = depth + 1
    for n in inv.nodes.values():
        n["children"] = sorted(n["children"], key=lambda c: (
            inv.nodes[c].get("nav_order") if isinstance(inv.nodes[c].get("nav_order"), int)
            else 10 ** 9, inv.nodes[c]["title"].lower()))

    nav_pages = sum(1 for n in inv.nodes.values() if n.get("src") == "nav")
    inv.stats_extra = {"visited": len(visited), "nav_sourced": nav_pages}
    return inv
