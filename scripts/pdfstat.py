#!/usr/bin/env python3
"""Print compact stats for a PDF: pages, outline entries, link annots, images, text."""
import os
import sys


def stats(path, deep_pages=200):
    out = {"bytes": os.path.getsize(path) if os.path.exists(path) else 0}
    with open(path, "rb") as fh:
        head = fh.read(5)
    if head != b"%PDF-":
        out["error"] = f"not-a-pdf head={head!r}"
        return out
    from pypdf import PdfReader

    r = PdfReader(path)
    pages = len(r.pages)
    out.update(pages=pages, outline=0, uri_links=0, internal_links=0,
               images=0, text_chars=0, helix_links=0, other_links=0)
    def walk(items):
        for it in items or []:
            if isinstance(it, list):
                walk(it)
            else:
                out["outline"] += 1
    try:
        walk(r.outline)
    except Exception:
        pass
    sample = ""
    for i, pg in enumerate(r.pages):
        try:
            for a in (pg.get("/Annots") or []):
                o = a.get_object()
                act = o.get("/A")
                if act is not None:
                    act = act.get_object()
                    uri = act.get("/URI")
                    if uri is not None:
                        out["uri_links"] += 1
                        if "helixops.ai" in str(uri):
                            out["helix_links"] += 1
                        else:
                            out["other_links"] += 1
                        continue
                if o.get("/Dest") is not None or (act is not None and act.get("/D") is not None):
                    out["internal_links"] += 1
        except Exception:
            pass
        if i < deep_pages:
            try:
                sample += pg.extract_text() or ""
            except Exception:
                pass
            try:
                out["images"] += len(list(r.pages[i].images))
            except Exception:
                pass
    out["text_chars"] = len(sample)
    out["text_sample"] = sample[:150].replace("\n", " / ")
    return out


if __name__ == "__main__":
    label = sys.argv[1]
    path = sys.argv[2]
    s = stats(path)
    if "error" in s:
        print(f"{label}: {s['error']} bytes={s['bytes']}")
    else:
        print(f"{label}: pages={s['pages']} outline={s['outline']} uri={s['uri_links']} "
              f"internal={s['internal_links']} helixuri={s['helix_links']} imgs={s['images']} "
              f"txt={s['text_chars']} bytes={s['bytes']}")
