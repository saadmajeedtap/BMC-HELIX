"""Target configuration and shared constants."""
from __future__ import annotations

import os
import re

#: Point this at a staging/private mirror with HELIX_BASE_URL to build elsewhere.
BASE = os.environ.get("HELIX_BASE_URL", "https://docs.helixops.ai").rstrip("/")
_base_host = re.sub(r"^https?://", "", BASE).split("/")[0].split(":")[0]

#: Absolute links to these hosts are treated as "the same documentation" even when
#: they are written with the old docs.bmc.com URL shape or as root-relative URLs.
DOC_HOSTS = tuple(sorted({h for h in (_base_host, "docs.helixops.ai", "docs.bmc.com") if h}))

#: The documentation space the user asked for.
DEFAULT_SPACE_PATH = "Service-Management/IT-Service-Management/BMC-Helix-ITSM/itsm263"
DEFAULT_PRODUCT = "BMC Helix ITSM"
DEFAULT_VERSION = "26.3"

USER_AGENT = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/126.0.0.0 Safari/537.36 (helix-offline-pdf; personal offline mirror)"
)

#: URL "actions" that are not readable documentation pages. Links pointing at them
#: are attachments/exports/edit-views, handled elsewhere or ignored.
NON_PAGE_ACTIONS = (
    "download", "image", "attach", "attachment", "edit", "create", "save", "preview",
    "export", "pdf", "viewrev", "viewattachrev", "jsx", "ssx", "code", "velocity",
    "delete", "cancel", "login", "register", "get", "print", "plain", "rdf",
)

# Never part of the readable documentation: XWiki app plumbing and BMC's authoring
# include-libraries. Filtered out of the inventory, but every filtered item is
# counted and listed in the report so nothing is dropped silently.
DENY_PATTERNS = [
    re.compile(r"(^|\.)_inclusionsLibrary", re.I),
    re.compile(r"(^|\.)[A-Za-z0-9_]+\.WebPreferences(\.|$)", re.I),
    re.compile(r"(^|\.)WebPreferences(\.|$)", re.I),
    re.compile(r"(^|\.)PDFViewer(\.|$)", re.I),
    re.compile(r"(^|\.)Translations(\.|$)", re.I),
    re.compile(r"(^|\.)TranslationCode(\.|$)", re.I),
    re.compile(r"(^|\.)AppWithinMinutes", re.I),
    re.compile(r"(^|\.)XWiki\.", re.I),
    re.compile(r"(^|\.)Code\.", re.I),
    re.compile(r"(^|\.)([A-Za-z0-9]+Template|Template)[.$]", re.I),
    re.compile(r"(^|\.)[A-Za-z0-9_]+Class(\.|$)", re.I),
]

IMAGE_EXT = {".png", ".jpg", ".jpeg", ".gif", ".svg", ".webp", ".bmp"}
ATTACH_EXT = {
    ".pdf", ".zip", ".csv", ".xlsx", ".xls", ".docx", ".doc", ".pptx", ".txt",
    ".json", ".xml", ".mp4", ".webm", ".mov", ".tgz", ".jar", ".vsix", ".md",
}



def space_dot(space_path: str) -> str:
    return space_path.replace("/", ".")


def norm_doc(doc: str) -> str:
    """Canonical page id. ``...Getting-started.WebHome`` == ``...Getting-started``."""
    d = (doc or "").strip().rstrip("/")
    d = d.split("#")[0].split("?")[0]
    while d.endswith(".WebHome"):
        d = d[: -len(".WebHome")]
    return d or "WebHome"


def doc_to_rel(doc: str, space_dot_name: str) -> str:
    d = doc
    if d.startswith(space_dot_name + "."):
        d = d[len(space_dot_name) + 1:]
    elif d == space_dot_name:
        d = ""
    return d.replace(".", "/")


def pretty_url(doc: str, space_path: str, space_dot_name: str) -> str:
    """The URL a human would open in a browser for this page."""
    rel = doc_to_rel(doc, space_dot_name)
    return f"{BASE}/bin/{space_path}/{rel}/" if rel else f"{BASE}/bin/{space_path}/"


def _first_path_segment(url: str) -> str:
    m = re.match(r"https?://[^/]+/([^/?#]+)", url)
    return m.group(1).lower() if m else ""


def _second_path_segment(url: str) -> str:
    m = re.match(r"https?://[^/]+/[^/]+/([^/?#]+)", url)
    return m.group(1).lower() if m else ""


_XREDIRECT = re.compile(r"/bin/login/[A-Za-z0-9/_-]*\?[A-Za-z0-9_&=-]*?xredirect=(?P<t>[^&\s]+)", re.I)


def unwrap_login_url(url: str) -> str:
    """Follow an XWiki login redirect to the page behind it.

    The portal wraps links to permission-gated pages as
    ``/bin/login/XWiki/XWikiLogin?xredirect=/bin/<space>/<Page>/``. The target is
    ordinary documentation, and leaving the wrapper in place means a link that we
    *could* answer from the PDF instead stays pointing at the website's login form.
    """
    if not url or "xredirect=" not in url:
        return url
    m = _XREDIRECT.search(url)
    if not m:
        return url
    from urllib.parse import unquote
    t = unquote(m.group("t"))
    if re.match(r"https?://", t):
        return t
    return BASE + (t if t.startswith("/") else "/" + t)


def url_to_doc(url: str, space_path: str, space_dot_name: str) -> str | None:
    """Map an in-space documentation URL to a canonical doc id (None if out of scope).

    Accepts the pretty form (``/bin/<space path>/<Page>/``), the explicit view form
    (``/bin/view/<space path>/<Page>``) and legacy ``docs.bmc.com/xwiki/bin/view/...``.
    Rejects attachment/action URLs (download/image/export/...).
    """
    if not url:
        return None
    u = unwrap_login_url(url.strip())      # links to gated pages hide behind a login URL
    if u.startswith("/") and not u.startswith("//"):
        u = BASE + u
    if not re.match(r"https?://", u):
        return None
    host = re.match(r"https?://([^/]+)", u).group(1).lower()
    host = host.rsplit(":", 1)[0] if re.search(r":\d+$", host) else host
    if host not in DOC_HOSTS:
        return None
    if _first_path_segment(u) == "bin":
        action = _second_path_segment(u)
        if action in NON_PAGE_ACTIONS:
            return None
        rest = re.sub(r"^https?://[^/]+/bin/(?:view/)?", "", u)
    elif u.lower().startswith((f"{BASE}/",)):
        rest = re.sub(r"^https?://[^/]+/", "", u)
    else:  # docs.bmc.com/xwiki/bin/view/...
        m = re.match(r"https?://[^/]+/xwiki/bin/(?:view/)?", u, re.I)
        if not m:
            return None
        rest = u[m.end():]
        action = ""
    rest = rest.split("?")[0].split("#")[0]
    segs = [s for s in rest.split("/") if s]
    sp = space_path.split("/")
    if segs[:len(sp)] != sp:
        return None
    segs = segs[len(sp):]
    while segs and segs[-1].lower() in ("webhome", "index.html", "view", ""):
        segs.pop()
    if not segs:
        return norm_doc(f"{space_dot_name}.WebHome")
    return norm_doc(f"{space_dot_name}." + ".".join(segs))


def is_denied(doc: str) -> bool:
    return any(p.search(doc) for p in DENY_PATTERNS)


def safe_name(doc: str) -> str:
    return re.sub(r"[^A-Za-z0-9._-]", "_", doc)[-150:]
