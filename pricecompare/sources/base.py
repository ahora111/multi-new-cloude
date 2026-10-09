from __future__ import annotations
from abc import ABC, abstractmethod
from datetime import datetime, timezone
from pathlib import Path
from ..extract import parse_price
from ..httpclient import HttpClient
from ..models import Offer, HealthResult, IN_STOCK, OUT_OF_STOCK, UNKNOWN_STOCK


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class Source(ABC):
    """One file per source. Subclass, implement `records()`, register in sources.yaml.

    `records()` yields plain dicts with keys:
      id, title, price, stock (any), url, image, color, storage, ram, brand, extra
    The base class turns them into `Offer`s and stamps the DECLARED currency unit;
    price-unit conversion happens in exactly one place (the pipeline), never here.
    """
    type_name = "base"

    def __init__(self, cfg, settings=None, http: HttpClient | None = None, base_dir: str = "."):
        self.cfg, self.name, self.o = cfg, cfg.name, cfg.options
        self.settings, self.base_dir = settings, base_dir
        self.note = ""          # free-text diagnostics shown next to the source status (e.g. which strategy was used)
        self.catalog_titles = []  # raw titles of the whole catalog (diagnostics: 'closest titles' for products not found)
        self.raw_count = None     # size of the whole catalog BEFORE watchlist filtering (used for the health check)
        self.http = http or HttpClient(
            rate_limit_per_sec=self.o.get("rate_limit_per_sec", 1.0), timeout=self.o.get("timeout", 20),
            retries=self.o.get("retries", 3), cache_dir=getattr(settings, "cache_dir", None),
            cache_ttl=getattr(settings, "cache_ttl_seconds", 300), headers=self.o.get("headers"),
            auth=self.o.get("auth"))

    # ---- helpers for subclasses ----
    def read(self, location: str) -> str:
        if location.startswith(("http://", "https://")):
            return self.http.get(location)
        p = Path(location)
        if not p.is_absolute():
            p = Path(self.base_dir) / p
        return p.read_text(encoding="utf-8")

    def locations(self, watchlist) -> list:
        locs = []
        for k in ("path", "url"):
            if self.o.get(k):
                locs.append(self.o[k])
        locs += list(self.o.get("urls") or [])
        tpl = self.o.get("search_url")
        if tpl:
            for w in watchlist or []:
                q = " ".join(x for x in [w.brand, w.model, f"{w.storage_gb}GB" if w.storage_gb else ""] if x)
                from urllib.parse import quote
                locs.append(tpl.replace("{query}", quote(q)))
        if not locs:
            raise ValueError(f"source {self.name}: configure 'path', 'url', 'urls' or 'search_url'")
        return locs

    def stock_of(self, raw) -> str:
        if raw is None or raw == "":
            return UNKNOWN_STOCK
        in_vals = {str(v).lower() for v in self.o.get("in_stock_values", [])}
        out_vals = {str(v).lower() for v in self.o.get("out_of_stock_values", [])}
        s = str(raw).strip().lower()
        if s in in_vals or s in ("in_stock", "instock", "available", "true", "yes", "1", "موجود"):
            return IN_STOCK
        if s in out_vals or s in ("out_of_stock", "outofstock", "unavailable", "false", "no", "0", "ناموجود"):
            return OUT_OF_STOCK
        try:
            return IN_STOCK if float(s) > 0 else OUT_OF_STOCK
        except ValueError:
            return UNKNOWN_STOCK

    # ---- contract ----
    @abstractmethod
    def records(self, watchlist) -> list:
        ...

    def fetch(self, watchlist) -> list:
        stamp, out = now_iso(), []
        for r in self.records(watchlist):
            if not r.get("title"):
                continue
            out.append(Offer(
                source=self.name, source_offer_id=str(r.get("id") or r["title"]), raw_title=str(r["title"]),
                price_raw=parse_price(r.get("price")), currency_unit_raw=self.cfg.currency_unit,
                stock=self.stock_of(r.get("stock")), url=str(r.get("url") or ""), image=str(r.get("image") or ""),
                fetched_at=stamp, raw_color=str(r.get("color") or ""), raw_storage=str(r.get("storage") or ""),
                raw_ram=str(r.get("ram") or ""), raw_brand=str(r.get("brand") or ""), extra=r.get("extra") or {}))
        return out

    def healthcheck(self) -> HealthResult:
        try:
            n = len(self.fetch([]))
        except Exception as exc:               # noqa: BLE001 - report, never raise
            return HealthResult(False, f"{exc.__class__.__name__}: {exc}", 0)
        need = self.cfg.min_expected_products
        return HealthResult(n >= need, f"{n} products (expected >= {need})", n)
