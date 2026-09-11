"""Polite, cached HTTP client (thread-safe, resumable)."""
from __future__ import annotations

import hashlib
import json
import os
import random
import threading
import time
from concurrent.futures import ThreadPoolExecutor

import requests

from .config import USER_AGENT


class Http:
    """GET/POST with an on-disk response cache so rebuilds are incremental.

    Cache layout: ``<cache_dir>/<sha1>.bin`` + ``<sha1>.meta.json`` (status, url,
    content-type, fetched-at). A rebuild re-reads the cache and touches the network
    only for misses.
    """

    def __init__(self, cache_dir, workers=8, delay=0.08, jitter=0.10, retries=4,
                 fresh=False, verbose=True):
        self.cache_dir = cache_dir
        self.workers = workers
        self.delay = delay
        self.jitter = jitter
        self.retries = retries
        self.fresh = fresh
        self.verbose = verbose
        os.makedirs(cache_dir, exist_ok=True)
        self._tls = threading.local()
        self._lock = threading.Lock()
        self.stats = {"requests": 0, "cache_hits": 0, "errors": 0, "retries": 0,
                      "bytes": 0}
        self._t0 = time.time()
        self._last = 0.0

    # ---------------------------------------------------------------- low level
    def _session(self):
        s = getattr(self._tls, "s", None)
        if s is None:
            s = requests.Session()
            s.headers.update({"User-Agent": USER_AGENT,
                              "Accept-Language": "en-US,en;q=0.9",
                              "Accept": "*/*"})
            self._tls.s = s
        return s

    def _throttle(self):
        wait = self.delay + random.uniform(0, self.jitter) - (time.time() - self._last)
        if wait > 0:
            time.sleep(wait)
        self._last = time.time()

    def _key(self, url, body=None):
        h = hashlib.sha1((url + "|" + (body or "")).encode()).hexdigest()
        return h

    def cached(self, url, body=None):
        k = self._key(url, body)
        binp = os.path.join(self.cache_dir, k + ".bin")
        metap = os.path.join(self.cache_dir, k + ".meta.json")
        if not self.fresh and os.path.exists(binp) and os.path.exists(metap):
            try:
                meta = json.load(open(metap))
                return meta["status"], open(binp, "rb").read(), meta.get("content_type", "")
            except Exception:
                return None
        return None

    def _store(self, url, body, status, ctype, body_name_hint=""):
        k = self._key(url)
        binp = os.path.join(self.cache_dir, k + ".bin")
        with open(binp, "wb") as fh:
            fh.write(body)
        json.dump({"url": url, "status": status, "content_type": ctype,
                   "bytes": len(body), "hint": body_name_hint,
                   "fetched_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())},
                  open(os.path.join(self.cache_dir, k + ".meta.json"), "w"))

    def get(self, url, binary=False, allow=(200,), max_bytes=None):
        """Return (status, bytes|text, content_type). None when it permanently failed."""
        hit = self.cached(url)
        if hit is not None:
            with self._lock:
                self.stats["cache_hits"] += 1
            status, body, ctype = hit
            return (status, body, ctype) if binary else (
                status, body.decode("utf-8", "replace"), ctype)
        last = None
        for attempt in range(self.retries):
            self._throttle()
            try:
                with self._lock:
                    self.stats["requests"] += 1
                r = self._session().get(url, timeout=90, stream=max_bytes is not None)
                if max_bytes is not None:
                    body = r.raw.read(max_bytes + 1, decode_content=True)
                else:
                    body = r.content
                ctype = r.headers.get("Content-Type", "")
                if r.status_code in allow:
                    self._store(url, body, r.status_code, ctype)
                    with self._lock:
                        self.stats["bytes"] += len(body)
                    return (r.status_code, body, ctype) if binary else (
                        r.status_code, body.decode("utf-8", "replace"), ctype)
                if r.status_code in (404, 410):
                    self._store(url, body, r.status_code, ctype)
                    return r.status_code, ("" if not binary else b""), ctype
                last = f"HTTP {r.status_code}"
                if r.status_code in (403, 429, 500, 502, 503, 504):
                    time.sleep(min(60, 2.0 * (2 ** attempt)) + random.uniform(0, 1))
                    with self._lock:
                        self.stats["retries"] += 1
                    continue
                break
            except Exception as exc:  # network hiccup -> backoff and retry
                last = repr(exc)
                time.sleep(min(30, 1.5 * (2 ** attempt)) + random.uniform(0, 1))
                with self._lock:
                    self.stats["retries"] += 1
        with self._lock:
            self.stats["errors"] += 1
        if self.verbose:
            print(f"[http] FAILED {url} ({last})", flush=True)
        return None

    # ------------------------------------------------------------- bulk helpers
    def get_many(self, urls, binary=False, max_bytes=None):
        """Parallel GETs. Returns {url: (status, body, ctype) | None}."""
        out = {}
        uniq = list(dict.fromkeys(u for u in urls if u))
        if not uniq:
            return out
        t0 = time.time()
        done = [0]

        def work(u):
            r = self.get(u, binary=binary, max_bytes=max_bytes)
            with self._lock:
                done[0] += 1
                n = done[0]
            if self.verbose and n % 500 == 0:
                el = time.time() - t0
                print(f"[http] {n}/{len(uniq)} ({el:.0f}s, "
                      f"{n / max(el, 1e-6):.1f}/s, hits={self.stats['cache_hits']}, "
                      f"err={self.stats['errors']})", flush=True)
            return u, r

        with ThreadPoolExecutor(max_workers=self.workers) as ex:
            for u, r in ex.map(work, uniq):
                out[u] = r
        return out

    def summary(self):
        s = dict(self.stats)
        s["seconds"] = round(time.time() - self._t0, 1)
        s["mb"] = round(s["bytes"] / 1e6, 1)
        return s
