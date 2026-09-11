#!/usr/bin/env python3
"""Cut a small, self-contained excerpt out of a big build PDF for visual QA.

Copies the front matter (cover + a couple of TOC pages) and a spread of content
pages into one small PDF, so a human (or the agent) can eyeball fidelity and check
that the page numbering / stamps / links survived, without moving 300 MB around.
"""
from __future__ import annotations

import argparse
import json
import os
import random

from pypdf import PdfReader, PdfWriter


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("pdf")
    ap.add_argument("--structure", default="")
    ap.add_argument("--out", default="excerpt.pdf")
    ap.add_argument("--pages", type=int, default=14)
    ap.add_argument("--seed", type=int, default=7)
    args = ap.parse_args()

    rd = PdfReader(args.pdf)
    n = len(rd.pages)
    picked = [0]
    structure = {}
    if args.structure and os.path.exists(args.structure):
        structure = json.load(open(args.structure)).get("structure", {})
        picked += [1, 2]
    starts = sorted({v["first_page"] - 1 for v in structure.values()})
    random.seed(args.seed)
    if starts:
        k = max(1, args.pages - len(picked))
        step = max(1, len(starts) // k)
        for i in starts[::step][:k]:
            picked.append(i)
    for _ in range(max(0, args.pages - len(picked))):
        picked.append(random.randrange(0, n))
    picked = sorted(set(p for p in picked if 0 <= p < n))
    w = PdfWriter()
    for i in picked:
        w.add_page(rd.pages[i])
    with open(args.out, "wb") as fh:
        w.write(fh)
    print(json.dumps({"out": args.out, "pages": len(picked), "indices": [p + 1 for p in picked],
                      "bytes": os.path.getsize(args.out)}))


if __name__ == "__main__":
    main()
