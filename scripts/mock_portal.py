#!/usr/bin/env python3
"""A miniature XWiki-shaped documentation portal, served on localhost.

Used by integration_test.py to exercise enumeration/fetch/cleaning against real
URL shapes (pretty ``/bin/<space>/<Page>/`` links, ``?sheet=XWiki.ExportDocumentTree``
lazy tree fragments, ``/bin/download/`` attachments, ``.xredirect`` pages) without
touching the public portal. Can also be run by hand:

    python3 scripts/mock_portal.py --port 8099
"""
from __future__ import annotations

import argparse
import io
import json
import re
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, unquote, urlparse

from PIL import Image

SPACE_PATH = "Demo/Space"
SPACE_DOT = "Demo.Space"
TREE_PATH = f"/bin/get/{SPACE_PATH}/WebHome/"

# doc -> (title, children, hidden_children_only_in_links)
SITE = {
    "WebHome": ("Home", ["Getting-started", "Administering"]),
    "Getting-started": ("Getting started", ["Getting-started.Page-a",
                                            "Getting-started.Old"]),
    "Getting-started.Page-a": ("Page A", ["Getting-started.Page-a.Sub"]),
    "Getting-started.Page-a.Sub": ("Page A sub", []),
    "Getting-started.Page-b": ("Page B (not in menu)", []),
    "Getting-started.Page-b.Deep": ("Deep page, menu-hidden, nested by name", []),
    "Getting-started.Old": ("Old name", []),
    "Administering": ("Administering", ["Administering.Deep-thing"]),
    "Administering.Deep-thing": ("Deep thing", []),
    "_inclusionsLibrary.Stuff": ("Internal include library", []),
}
ATTACH = {
    "diagram.png": "image/png",
    "notes.pdf": "application/pdf",
}


def png_bytes():
    buf = io.BytesIO()
    Image.new("RGB", (240, 140), (20, 90, 170)).save(buf, format="PNG")
    return buf.getvalue()


def pdf_bytes():
    return b"%PDF-1.4\n1 0 obj<</Type/Catalog>>endobj\ntrailer<</Root 1 0 R>>\n%%EOF\n"


def rel_of(doc):
    return doc.replace(".", "/")


def nav_html(current=""):
    """Left navigation as the portal renders it: a nested ul/li tree, in menu order,
    with the real titles. Pages hidden from the menu are absent here by design."""

    def render(keys):
        out = []
        for k in keys:
            title, kids = SITE[k][0], SITE[k][1]
            sub = render(kids) if kids else ""
            mark = ' class="active"' if k == current else ""
            out.append(f'<li{mark} data-reference="{SPACE_DOT}.{k}">'
                       f'<a href="/bin/{SPACE_PATH}/{rel_of(k)}/">{title}</a>{sub}</li>')
        return "<ul>" + "".join(out) + "</ul>"

    return (f'<div id="left-navigation" class="helix-nav">'
            f'{render(SITE["WebHome"][1])}</div>')


def page_html(doc):
    title, kids = SITE[doc][0], SITE[doc][1]
    slug = doc or "root"
    links = "".join(
        f'<p>See <a href="/bin/{SPACE_PATH}/{rel_of(k)}/">{k}</a></p>' for k in kids)
    extra = ""
    if doc == "Getting-started.Page-a":
        extra = ('<p>Linked but hidden from the menu: '
                 '<a href="/bin/Demo/Space/Getting-started/Page-b/">page b</a>, '
                 '<a href="/bin/Demo/Space/Getting-started/Page-b/Deep/">deep page b</a>, '
                 'legacy relative link: <a href="Old/">old name</a> and '
                 '<a href="/bin/Demo/Space/Administering.Deep-thing/">dotted link</a></p>'
                 '<p>Attachment: <a href="/bin/download/Demo.Space.Getting-started.Page-a/notes.pdf?rev=1.1">'
                 'release notes pdf</a></p>'
                 '<p><a href="https://www.youtube.com/watch?v=demo123">video</a></p>')
    hidden = (f'<div class="xwiki-tabgroups">'
              f'<ul class="nav-tabs"><li><a href="#t1">Before you begin</a></li>'
              f'<li><a href="#t2">Procedure</a></li></ul>'
              f'<div class="tab-content">'
              f'<div class="tab-pane active" id="t1"><p>VISIBLE-TAB1-{slug}</p></div>'
              f'<div class="tab-pane" id="t2" style="display:none"><p>HIDDEN-TAB2-{slug}</p></div>'
              f'</div></div>'
              f'<div class="collapse" style="display:none"><p>COLLAPSED-{slug}</p></div>'
              f'<details><summary>more</summary><p>DETAILS-{slug}</p></details>'
              f'<div aria-hidden="true"><p>ARIAHIDDEN-{slug}</p></div>')
    table = (f'<table><thead><tr><th>Option</th><th>Meaning</th></tr></thead><tbody>'
             f'<tr><td>mode</td><td>TABLE-ROW-{slug}</td></tr></tbody></table>')
    img = (f'<figure><img src="/bin/download/Demo.Space.{doc or "WebHome"}/diagram.png?rev=1.1">'
           f'<figcaption>Figure for {slug}</figcaption></figure>')
    body = (f'<html><head><title>{title}</title></head><body>'
            f'<nav class="xwikiDocumentTree">NAVJUNK-{slug}</nav>'
            f'{nav_html(doc)}'
            f'<h1 id="contentTitle">{title}</h1>'
            f'<div id="xwikicontent">'
            f'<p>INTRO-{slug} line one.</p>'
            f'{hidden}{table}{img}{links}{extra}'
            f'</div><footer>FOOTERJUNK-{slug}</footer></body></html>')
    return body


def redirect_html(doc):
    return (f'<html><body><h1 id="contentTitle">{SITE[doc][0]}</h1>'
            f'<div id="xwikicontent"><div class="xredirect">'
            f'<p>This page redirects to '
            f'<a href="/bin/{SPACE_PATH}/Getting-started/Page-a/">Page A</a></p>'
            f'</div></div></body></html>')


def home_html():
    """The space landing page: also carries the tree endpoint the real site embeds."""
    tree = (f'<div class="pageTree" data-url="{TREE_PATH}?outputSyntax=plain'
            f'&amp;sheet=XWiki.ExportDocumentTree&amp;filterHiddenDocuments=false'
            f'&amp;limit=10&amp;root=document%3Axwiki%3A{SPACE_DOT}.WebHome"></div>')
    kids = "".join(f'<li><a href="/bin/{SPACE_PATH}/{k}/">{SITE[k][0]}</a></li>'
                   for k in SITE["WebHome"][1])
    return (f'<html><body><h1 id="contentTitle">Home</h1><div id="xwikicontent">'
            f'<p>INTRO-root portal home.</p>{tree}<ul>{kids}</ul>'
            f'<p><a href="/bin/Demo/Space/_inclusionsLibrary/Stuff/">authoring include</a>'
            f'<a href="/bin/get/Demo/Space/WebHome?outputSyntax=plain&amp;sheet=XWiki.ExportDocumentTree&amp;limit=10&amp;root=document%3Axwiki%3ADemo.Space.WebHome">tree</a></p>'
            f'</div></body></html>')


def tree_fragment(root_ref):
    root = unquote(root_ref).replace("document:", "").replace("xwiki:", "")
    root = re.sub(r"\.WebHome$", "", root)
    key = "" if root in (SPACE_DOT, f"{SPACE_PATH}", "") else root[len(SPACE_DOT) + 1:]
    if key in ("", "WebHome", SPACE_DOT):
        key = "WebHome"
    if key not in SITE:
        return None, 404
    kids = SITE[key][1]
    items = []
    for k in kids:
        closed = "closed" if SITE[k][1] else ""
        href = f"/bin/view/{SPACE_PATH}/{rel_of(k)}/"
        items.append(f'<li class="{closed}" data-reference="{SPACE_DOT}.{k}">'
                     f'<a href="{href}">{SITE[k][0]}</a></li>')
    frag = f'<ul class="tree">{"".join(items)}</ul>' if kids else "<ul class=\"tree\"></ul>"
    return frag, 200


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def _send(self, code, body, ctype="text/html;charset=UTF-8"):
        if isinstance(body, str):
            body = body.encode()
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        u = urlparse(self.path)
        path, q = u.path, parse_qs(u.query)
        if path.startswith("/bin/get/") or ("sheet=" in u.query):
            frag, code = tree_fragment(q.get("root", [""])[0])
            return self._send(code, frag or "<ul></ul>")
        if path.startswith("/bin/download/"):
            fname = path.rsplit("/", 1)[-1]
            if fname == "diagram.png":
                return self._send(200, png_bytes(), "image/png")
            if fname == "notes.pdf":
                return self._send(200, pdf_bytes(), "application/pdf")
            return self._send(404, "no such attachment", "text/plain")
        if path.startswith("/bin/"):
            rel = re.sub(r"^/bin/(?:view/)?" + re.escape(SPACE_PATH) + r"/", "", path)
            rel = rel.strip("/")
            doc = rel.replace("/", ".")
            doc = re.sub(r"\.WebHome$", "", doc)
            if doc in ("", "WebHome"):
                return self._send(200, home_html())
            if doc in SITE:
                if doc == "Getting-started.Old":
                    return self._send(200, redirect_html(doc))
                return self._send(200, page_html(doc))
        return self._send(404, "<html><body>404</body></html>")


class Server:
    def __init__(self, port=0):
        self.httpd = ThreadingHTTPServer(("127.0.0.1", port), Handler)
        self.port = self.httpd.server_address[1]
        self.thread = threading.Thread(target=self.httpd.serve_forever, daemon=True)

    def __enter__(self):
        self.thread.start()
        return self

    def __exit__(self, *a):
        self.httpd.shutdown()
        self.httpd.server_close()

    @property
    def base(self):
        return f"http://127.0.0.1:{self.port}"


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=8099)
    a = ap.parse_args()
    with Server(a.port) as s:
        print(json.dumps({"base": s.base, "tree": f"{s.base}{TREE_PATH}?root=document%3Axwiki%3A{SPACE_DOT}.WebHome"}))
        print("serving; Ctrl-C to stop")
        s.thread.join()
