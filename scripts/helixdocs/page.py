"""Fetch a documentation page and turn it into a standalone, print-ready HTML file.

Everything the browser hides behind tabs, accordions, "show more" toggles or
``display:none`` is expanded, because the PDF has to contain every line. Links to
pages of this documentation space are rewritten to canonical absolute portal URLs
which the assembler converts into *in-document* destinations, so clicking them
never leaves the PDF.
"""
from __future__ import annotations

import hashlib
import os
import re
from urllib.parse import unquote, urljoin, urlsplit

from bs4 import BeautifulSoup

from .config import ATTACH_EXT, BASE, IMAGE_EXT, is_denied, pretty_url, safe_name, url_to_doc

STRIP_SELECTORS = [
    "script", "style", "link[rel=stylesheet]", "noscript", "iframe", "object",
    "embed", "form", "button", "input", "select", "textarea", "svg.icon", "canvas",
    "#xwikimainmenu", "#main-header", "#main-navigation", "#leftColumn",
    "#header", "#footer", "#document-footer", "#contentFooter", ".document-footer",
    "#tm-bottom", ".breadcrumbs", "#xwikihead", "#editbuttons", ".page-location",
    ".on-this-page", "#toc", ".toc", "#main-inner-content>nav", "nav.navbar",
    ".xwikiDocumentTree", ".bmc-document-tree", ".pageTree", "#pageTree",
    ".bmc-export-modal", ".modal", ".popover", ".tooltip", "#xwikilogin",
    ".announcement", "#announcements", ".survey", ".bmc-feedback", "#feedback",
    ".rating", ".star-rating", ".addthis", ".social-links", ".breadcrumbs-nav",
    "#HelixDocNavigationUIX", ".ai-answer", ".searchSuggest", "#liveHelp",
    ".bmc-page-tools", ".document-toc", ".doc-toc", ".xcomment", ".comment",
    "#comments", ".attachments-title", "img[src*=logo]", "img[src*=banner]",
]

# Anything the site hides with these must become visible in the PDF.
FORCE_SHOW_CSS = """
  .collapse:not(.hx-noexpand), .collapsing, [hidden], .hidden, .invisible,
  .d-none, .tab-pane, .accordion-body, .xwiki-hidden, .hx-hidden,
  .bmc-collapsed-content, .macro-layout-section { display:block !important;
      visibility:visible !important; height:auto !important; max-height:none !important;
      overflow:visible !important; opacity:1 !important; }
"""

PAGE_CSS = """
@page { size: A4; margin: 15mm 14mm 16mm 14mm; }
* { box-sizing: border-box; }
html, body { margin:0; padding:0; color:#16181d;
  font-family:"DejaVu Sans","Liberation Sans",Arial,Helvetica,sans-serif;
  font-size:9.3pt; line-height:1.42; }
body { orphans:3; widows:3; }
h1, h2, h3, h4, h5, h6 { font-family:"DejaVu Sans","Liberation Sans",Arial,sans-serif;
  color:#0b2e59; line-height:1.25; margin:14px 0 6px; break-after:avoid; break-inside:avoid; }
h1 { font-size:16.5pt; border-bottom:2px solid #0663a1; padding-bottom:4px; margin-top:0; }
h2 { font-size:13pt; }
h3 { font-size:11.2pt; }
h4 { font-size:10pt; }
h5, h6 { font-size:9.5pt; }
p { margin:0 0 6px; }
a { color:#0b5cad; text-decoration:none; }
ul, ol { margin:0 0 7px; padding-left:20px; }
li { margin:0 0 3px; }
li > ul, li > ol { margin-top:3px; }
table { border-collapse:collapse; width:100%; margin:8px 0 10px; font-size:8.4pt;
  max-width:100%; }
th, td { border:1px solid #b9c2cc; padding:4px 6px; vertical-align:top;
  text-align:left; break-inside:avoid; word-break:break-word; overflow-wrap:anywhere; }
.hyphenation, body { hyphens:none; text-align:left; }
.macro-layout, .table-responsive, .bmc-table-responsive-wrapper { overflow:visible !important; }
th { background:#eef3f8; font-weight:bold; }
tr { break-inside:avoid; }
thead { display:table-header-group; }
pre { background:#f5f7fa; border:1px solid #d7dee6; border-radius:3px; padding:6px 8px;
  font-family:"DejaVu Sans Mono","Liberation Mono",Consolas,monospace; font-size:7.6pt;
  line-height:1.35; white-space:pre-wrap; word-break:break-word; margin:7px 0; }
code { font-family:"DejaVu Sans Mono","Liberation Mono",Consolas,monospace;
  font-size:8.2pt; background:#f1f4f8; padding:0 2px; border-radius:2px; }
kbd, samp { font-family:"DejaVu Sans Mono",monospace; font-size:8pt; }
img, svg, video, figure { max-width:100%; height:auto; }
figure { margin:8px 0; break-inside:avoid; }
figcaption { font-size:8pt; color:#4b5563; margin-top:3px; }
.note, .tip, .info, .important, .warning, .caution, .alert, .callout,
.xwiki-notification, .doc-alert { border-left:4px solid #0663a1; background:#f1f7fd;
  padding:6px 10px; margin:8px 0; break-inside:avoid; }
.warning, .caution, .danger, .alert-danger { border-left-color:#c33; background:#fdf3f3; }
.important, .alert-warning { border-left-color:#d97706; background:#fdf8ee; }
blockquote { border-left:3px solid #cbd5e1; margin:8px 0; padding:2px 12px; color:#374151; }
hr { border:0; border-top:1px solid #d7dee6; margin:10px 0; }
dl { margin:0 0 8px; } dt { font-weight:bold; margin-top:6px; } dd { margin:0 0 6px 16px; }
sup, sub { font-size:7pt; }
.hx-crumb { font-size:7.6pt; color:#5b6470; margin:0 0 3px; text-transform:none; }
.hx-src { font-size:7.2pt; color:#7a828c; margin:12px 0 0; border-top:1px dotted #cbd5e1;
  padding-top:3px; }
.hx-tabhead { font-size:10pt; font-weight:bold; color:#0b2e59; margin:12px 0 4px;
  border-bottom:1px solid #dbe3ec; padding-bottom:2px; }
.hx-embed { font-size:8.2pt; color:#4b5563; background:#f5f7fa; border:1px dashed #cbd5e1;
  padding:4px 8px; margin:6px 0; }
.hx-attach { font-size:8.2pt; color:#374151; }
.hx-empty { color:#7a828c; font-style:italic; }
FORCE_SHOW
"""


def _abs(base, href):
    try:
        return urljoin(base, unquote(href or ""))
    except Exception:
        return href or ""


def _ext(url):
    p = urlsplit(url).path.lower()
    return os.path.splitext(p)[1]


class PageBuilder:
    """Turns portal HTML into one standalone HTML file plus metadata."""

    def __init__(self, http, space_path, out_dir, mirror_attachments=True,
                 max_asset_bytes=40 * 1024 * 1024, known_docs=None, parent_map=None):
        self.http = http
        self.space_path = space_path
        self.space_dot = space_path.replace("/", ".")
        self.out_dir = out_dir
        self.pages_dir = os.path.join(out_dir, "pages")
        self.assets_dir = os.path.join(out_dir, "assets")
        self.attach_dir = os.path.join(out_dir, "attachments")
        for d in (self.pages_dir, self.assets_dir, self.attach_dir):
            os.makedirs(d, exist_ok=True)
        self.mirror_attachments = mirror_attachments
        self.max_asset_bytes = max_asset_bytes
        self.known_docs = known_docs or set()
        self.parent_map = parent_map or {}
        self._asset_index = {}

    # ------------------------------------------------------------------ links
    def resolve_link(self, absu):
        """Absolute portal URL -> (canonical doc id, how).

        Handles the shapes the portal really uses plus the sloppy ones authors
        leave behind: relative sibling links resolved against a pretty URL point
        one level too deep, so a link whose target does not exist is retried as a
        sibling of its parent.
        """
        d = url_to_doc(absu, self.space_path, self.space_dot)
        if not d:
            return None, None
        known = self.known_docs
        if not known or d in known:
            return d, "direct"
        # not a page we know of: the naive interpretation of a relative link can
        # sit one level too deep, so also try it as a sibling of its parent.
        parts = d.split(".")
        for i in range(len(parts) - 1, 2, -1):
            head, tail = ".".join(parts[:i]), parts[i]
            par = self.parent_map.get(head)
            cand = f"{par}.{tail}" if par else None
            if cand and cand in known:
                return cand, "sibling-recovered"
        # neither form is known: keep the naive one so the closure pass can
        # discover pages the navigation hides, and record it for the report.
        return d, "unverified"

    # ------------------------------------------------------------------ assets
    def _localize(self, url, doc=None, kind="asset"):
        """Download a portal asset and return (file_url|None, note)."""
        if not url or url.startswith(("data:", "javascript:", "mailto:", "tel:")):
            return None, "skip"
        if url.startswith("/"):
            url = BASE + url
        key = hashlib.sha1(url.encode()).hexdigest()[:20]
        cached = self._asset_index.get(key)
        ext = _ext(url) or (".png" if kind == "image" else ".bin")
        if kind == "attach":
            fname = unquote(os.path.basename(urlsplit(url).path)) or (key + ext)
            dest = os.path.join(self.attach_dir, f"{safe_name(doc or 'misc')}__{fname}")
        else:
            dest = os.path.join(self.assets_dir, key + ext)
        if cached and os.path.exists(cached):
            return "file://" + cached, "cached"
        r = self.http.get(url, binary=True, max_bytes=self.max_asset_bytes)
        if r is None:
            return None, "download-failed"
        status, body, ctype = r
        if status != 200 or not body:
            return None, f"http-{status}"
        os.makedirs(os.path.dirname(dest), exist_ok=True)
        if not (os.path.exists(dest) and os.path.getsize(dest) == len(body)):
            with open(dest, "wb") as fh:
                fh.write(body)
        self._asset_index[key] = dest
        return "file://" + dest, "ok"

    # -------------------------------------------------------------------- main
    def build(self, doc, html, title_hint="", crumbs=None):
        """Return metadata dict; writes build/pages/<slug>.html."""
        meta = {"doc": doc, "title": title_hint, "words": 0, "text_chars": 0,
                "images": 0, "tables": 0, "links_internal": 0, "links_external": 0,
                "attachments": [], "is_redirect": False, "redirect_to": None,
                "found_docs": [], "filtered_refs": [], "unresolved_links": [],
                "notes": []}
        base = pretty_url(doc, self.space_path, self.space_dot)
        soup = BeautifulSoup(html or "", "lxml")

        # ---- redirect?  (XWiki renders a short notice + one link)
        node = soup.select_one(".xredirect, #xwikicontent .redirect")
        if node is None:
            t = (soup.get_text(" ", strip=True) or "")[:400].lower()
            if "this page redirects to" in t or "has been moved to" in t:
                node = soup.select_one("#xwikicontent") or soup.body
        if node is not None:
            a = node.find("a", href=True)
            tgt = url_to_doc(_abs(base, a["href"]), self.space_path, self.space_dot) if a else None
            if True:
                meta["is_redirect"] = True
                meta["redirect_to"] = tgt
                meta["notes"].append("redirect" if tgt else "redirect-target-unresolved")
                meta["text_chars"] = len(html or "")
                return meta

        # ---- content root
        root = soup.select_one("#xwikicontent") or soup.select_one("#contentInner") \
            or soup.select_one("main") or soup.body
        h1 = soup.select_one("#contentTitle") or soup.select_one("h1")
        title = (h1.get_text(" ", strip=True) if h1 else "") or title_hint \
            or doc.rsplit(".", 1)[-1].replace("-", " ")
        meta["title"] = re.sub(r"\s+", " ", title).strip()

        if root is None:
            meta["notes"].append("no-content-root")
            root = soup.new_tag("div")
            soup.append(root)

        for sel in STRIP_SELECTORS:
            try:
                for el in root.select(sel):
                    if el.name == "link":
                        continue
                    el.decompose()
            except Exception:
                pass
        # drop the site's own nav/related-widgets even if selectors missed
        for el in list(root.find_all(True)):
            cls = " ".join(el.get("class") or [])
            if re.search(r"(documentTree|pageTree|navigation|breadcrumbs|onThisPage|"
                         r"exportModal|editButtons|feedback|announcement|helix-nav)",
                         cls, re.I) and el.name in ("div", "nav", "ul", "section"):
                if el.find(["p", "table", "li", "h2", "h3"]) is None:
                    el.decompose()

        # ---- expand every JS-hidden container, give each tab a real heading
        tabs = root.select(".xwiki-tabgroups, .tabbable, div[data-tabs]")
        for tg in tabs:
            labels = {}
            for li in tg.select("ul.nav-tabs li a, ul.nav-tabs>li>a, .nav-link"):
                href = li.get("href") or li.get("data-target") or ""
                tid = href.split("#")[-1].strip()
                if tid:
                    labels[tid] = li.get_text(" ", strip=True)
            for pane in tg.select(".tab-pane, .tab-content > div"):
                pid = (pane.get("id") or "").strip()
                label = labels.get(pid)
                if label:
                    pane.insert(0, BeautifulSoup(
                        f'<div class="hx-tabhead">{label}</div>', "lxml").div)
                pane.attrs.pop("style", None)
                cls = [c for c in (pane.get("class") or []) if c not in ("hide", "hidden")]
                pane["class"] = cls
        for el in root.select("[style]"):
            st = el.get("style") or ""
            if re.search(r"display\s*:\s*none|visibility\s*:\s*hidden|max-height\s*:\s*0",
                         st, re.I):
                new = re.sub(r"(display\s*:\s*none|visibility\s*:\s*hidden"
                             r"|max-height\s*:\s*0)[^;]*;?", "", st, flags=re.I)
                if new.strip():
                    el["style"] = new
                else:
                    del el["style"]
        for el in root.select("[aria-hidden=true], .collapse, .accordion-body, details"):
            if el.name == "details":
                el["open"] = ""
            else:
                el.attrs.pop("aria-hidden", None)
        for el in root.select(".hidden-print"):
            el.attrs.pop("class", None)

        # ---- iframes / videos -> textual pointer (kept, but not clickable)
        for el in root.select("[data-src], .video-container, .bmc-video"):
            src = el.get("data-src") or ""
            if src:
                rep = soup.new_tag("div")
                rep["class"] = ["hx-embed"]
                rep.string = f"Video/interactive content: {src}"
                el.replace_with(rep)

        # ---- ids / anchors: prefix so they can never collide, keep in-page links
        slug = safe_name(doc)
        idmap = {}
        for el in root.select("[id]"):
            old = el["id"]
            new = f"{slug}__{old}"
            idmap[old] = new
            el["id"] = new

        # ---- images + attachments
        for img in root.find_all("img"):
            src = img.get("src") or img.get("data-src") or ""
            if not src:
                parent_a = img.find_parent("a", href=True)
                src = parent_a["href"] if parent_a else ""
            src_abs = _abs(base, src)
            if _ext(src_abs) in IMAGE_EXT and src_abs:
                furl, note = self._localize(src_abs, doc, "image")
                if furl:
                    img["src"] = furl
                    meta["images"] += 1
                else:
                    img.decompose()
                    meta["notes"].append(f"img:{note}")
            elif not src_abs:
                img.decompose()
            else:
                img["src"] = src_abs
                img["class"] = (img.get("class") or []) + ["hx-remote-img"]
        for src in root.find_all("source"):
            src.decompose()

        # ---- links
        for a in root.find_all("a"):
            href = a.get("href") or ""
            if not href:
                a.attrs.pop("href", None)
                continue
            if href.startswith("#"):
                tgt = idmap.get(href[1:])
                if tgt:
                    a["href"] = "#" + tgt
                else:
                    a.attrs.pop("href", None)
                    a["class"] = (a.get("class") or []) + ["hx-dead-anchor"]
                continue
            absu = _abs(base, href)
            d, how = self.resolve_link(absu)
            if how == "sibling-recovered":
                meta["notes"].append(f"recovered-link:{d}")
            if how == "unverified":
                meta["unresolved_links"].append(absu)
            if d:
                if is_denied(d):
                    meta["filtered_refs"].append(d)
                    d = None
            if d:
                meta["found_docs"].append(d)
                # canonical absolute portal URL: the assembler turns these into
                # in-document destinations (so they never hit the web)
                a["href"] = pretty_url(d, self.space_path, self.space_dot) + \
                    (("#" + href.split("#", 1)[1]) if "#" in href else "")
                a["class"] = (a.get("class") or []) + ["hx-internal"]
                meta["links_internal"] += 1
            else:
                ext = _ext(absu)
                if ext in ATTACH_EXT or re.match(r"https?://[^/]+/bin/(download|image)/",
                                                 absu):
                    fname = unquote(os.path.basename(urlsplit(absu).path)) or "attachment"
                    meta["attachments"].append({"doc": doc, "name": fname, "url": absu})
                    if self.mirror_attachments:
                        furl, note = self._localize(absu, doc, "attach")
                        meta["attachments"][-1]["mirrored"] = bool(furl)
                        meta["attachments"][-1]["local"] = (furl or "").replace("file://", "")
                    span = soup.new_tag("span")
                    span["class"] = ["hx-attach"]
                    span.string = "".join(a.stripped_strings) or fname
                    inner = BeautifulSoup(
                        f'<span class="hx-attach">{span.string} &nbsp;[attachment: '
                        f'{fname}]</span>', "lxml").span
                    a.replace_with(inner)
                else:
                    a["href"] = absu
                    a["class"] = (a.get("class") or []) + ["hx-external"]
                    meta["links_external"] += 1

        # ---- avoid printing the page title twice
        first = root.find(["h1", "h2"])
        if first is not None and re.sub(r"\s+", " ", first.get_text(" ", strip=True)).strip() \
                == meta["title"]:
            first.decompose()

        # ---- tables/figures sanity
        meta["tables"] = len(root.find_all("table"))

        # ---- content quality flags
        text = re.sub(r"\s+", " ", root.get_text(" ", strip=True))
        meta["text_chars"] = len(text)
        meta["words"] = len(text.split())
        if meta["text_chars"] < 40:
            meta["notes"].append("suspiciously-short-content")
        if meta["words"] > 90000:
            meta["notes"].append("huge-page")

        crumb = " \u203a ".join([meta.get("product", ""), *(crumbs or [])][-8:])
        body_html = (f'<!DOCTYPE html><html lang="en"><head><meta charset="utf-8">'
                     f'<title>{meta["title"]}</title>'
                     f'<style>{PAGE_CSS.replace("FORCE_SHOW", FORCE_SHOW_CSS)}</style>'
                     f'</head><body><section class="hx-page" id="hx-{slug}">'
                     f'<h1>{meta["title"]}</h1>'
                     f'<div class="hx-crumb">{crumb} &nbsp;\u00b7\u00b7&nbsp; {doc}</div>'
                     f'{str(root)}'
                     f'<div class="hx-src">BMC Helix documentation · {base}</div>'
                     f'</section></body></html>')
        out = os.path.join(self.pages_dir, f"{slug}.html")
        with open(out, "w", encoding="utf-8") as fh:
            fh.write(body_html)
        meta["html_file"] = out
        meta["html_bytes"] = len(body_html)
        return meta


def crumbs_for(inv, doc, limit=4):
    """Ancestor titles, outermost first (used as a breadcrumb on each page)."""
    out, node = [], inv.nodes.get(doc)
    while node is not None and len(out) < limit:
        out.append(node.get("title") or "")
        pid = node.get("parent")
        node = inv.nodes.get(pid) if pid else None
    return list(reversed([t for t in out if t]))


def fetch_pages(http, inv, builder, docs, verbose=True):
    """Download + clean each doc; returns {doc: meta} (meta=None on failure)."""
    urls = {d: inv.nodes[d]["url"] for d in docs}
    res = http.get_many(list(urls.values()))
    metas = {}
    for d, u in urls.items():
        r = res.get(u)
        if r is None:
            metas[d] = None
            continue
        status, html, ctype = r
        if status != 200:
            metas[d] = {"doc": d, "error": f"http-{status}", "title": inv.nodes[d]["title"],
                        "text_chars": 0, "words": 0, "images": 0, "tables": 0,
                        "links_internal": 0, "links_external": 0, "attachments": [],
                        "found_docs": [], "filtered_refs": [], "unresolved_links": [],
                        "is_redirect": False, "redirect_to": None, "notes": []}
            continue
        metas[d] = builder.build(d, html, title_hint=inv.nodes[d]["title"],
                                 crumbs=crumbs_for(inv, d))
    if verbose:
        ok = sum(1 for m in metas.values() if m and "error" not in m)
        print(f"[fetch] cleaned {ok}/{len(docs)} pages "
              f"(http stats: {http.summary()})", flush=True)
    return metas
