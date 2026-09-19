"""Polite HTTP: rate limit, retries with exponential backoff, Retry-After, disk cache, env-based auth."""
from __future__ import annotations
import hashlib
import os
import time
from pathlib import Path
import requests

USER_AGENT = "pricecompare/1.0 (+personal price comparison; contact: set PRICECOMPARE_CONTACT)"


class HttpError(Exception):
    pass


class HttpClient:
    def __init__(self, rate_limit_per_sec=1.0, timeout=20, retries=3, backoff=1.0, cache_dir=None,
                 cache_ttl=300, headers=None, auth=None, sleep=time.sleep, session=None):
        self.min_interval = 1.0 / rate_limit_per_sec if rate_limit_per_sec else 0.0
        self.timeout, self.retries, self.backoff = timeout, retries, backoff
        self.cache_dir = Path(cache_dir) if cache_dir else None
        self.cache_ttl = cache_ttl
        self.sleep = sleep
        self.session = session or requests.Session()
        self.headers = {"User-Agent": os.environ.get("PRICECOMPARE_UA", USER_AGENT), **(headers or {})}
        self.auth = self._auth(auth)
        self._last = 0.0

    @staticmethod
    def _auth(cfg):
        if not cfg:
            return None
        kind = cfg.get("type")
        if kind == "header":
            val = os.environ.get(cfg["env"])
            if not val:
                raise HttpError(f"missing environment variable {cfg['env']} (auth)")
            return ("header", cfg["name"], val)
        if kind == "basic":
            u, p = os.environ.get(cfg["user_env"]), os.environ.get(cfg["password_env"])
            if not u or not p:
                raise HttpError(f"missing environment variables {cfg['user_env']}/{cfg['password_env']} (auth)")
            return ("basic", u, p)
        raise HttpError(f"unknown auth type {kind!r}")

    def _cache_path(self, url):
        return self.cache_dir / (hashlib.sha1(url.encode()).hexdigest() + ".txt") if self.cache_dir else None

    def get(self, url: str) -> str:
        cp = self._cache_path(url)
        if cp and cp.exists() and time.time() - cp.stat().st_mtime < self.cache_ttl:
            return cp.read_text(encoding="utf-8")
        headers, auth = dict(self.headers), None
        if self.auth:
            if self.auth[0] == "header":
                headers[self.auth[1]] = self.auth[2]
            else:
                auth = (self.auth[1], self.auth[2])
        last_err = None
        for attempt in range(self.retries + 1):
            wait = self.min_interval - (time.monotonic() - self._last)
            if wait > 0:
                self.sleep(wait)
            try:
                self._last = time.monotonic()
                r = self.session.get(url, headers=headers, auth=auth, timeout=self.timeout)
                if r.status_code == 429 or r.status_code >= 500:
                    delay = self.backoff * 2 ** attempt
                    try:
                        delay = max(delay, float(r.headers.get("Retry-After", 0)))
                    except ValueError:
                        pass
                    last_err = HttpError(f"HTTP {r.status_code} for {url}")
                    if attempt < self.retries:
                        self.sleep(delay)
                        continue
                    raise last_err
                if r.status_code >= 400:
                    raise HttpError(f"HTTP {r.status_code} for {url}")   # deterministic: no retry
                r.encoding = r.encoding or "utf-8"
                text = r.text
                if cp:
                    cp.parent.mkdir(parents=True, exist_ok=True)
                    cp.write_text(text, encoding="utf-8")
                return text
            except (requests.ConnectionError, requests.Timeout) as exc:
                last_err = HttpError(f"network error for {url}: {exc.__class__.__name__}")
                if attempt < self.retries:
                    self.sleep(self.backoff * 2 ** attempt)
                    continue
                raise last_err
        raise last_err or HttpError("unreachable")
