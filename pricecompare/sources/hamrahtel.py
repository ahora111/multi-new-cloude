"""Hamrahtel quick-checkout source (Playwright). Wraps the original scraper in sources/vendor/.

sources.yaml:
  - name: hamrahtel
    type: hamrahtel
    currency_unit: toman
    min_expected_products: 20      # the original project used 20 as the anomaly threshold
    categories: [mobile]           # mobile | laptop | tablet | console
    page_timeout_ms: 90000
    scrape_attempts: 3
    max_scrolls: 20
    legacy_skip_items: 25
Requires:  pip install playwright && playwright install chromium
"""
from __future__ import annotations
import importlib
from types import SimpleNamespace
from .base import Source


def _scraper():
    try:
        return importlib.import_module("pricecompare.sources.vendor.hamrahtel_scraper")
    except ImportError as exc:                                        # pragma: no cover - env specific
        raise RuntimeError("Hamrahtel needs Playwright: pip install playwright && playwright install chromium") from exc


class HamrahtelSource(Source):
    type_name = "hamrahtel"

    def records(self, watchlist):
        scraper = _scraper()
        wanted = self.o.get("categories") or ["mobile"]
        unknown = [c for c in wanted if c not in scraper.CATEGORIES]
        if unknown:
            raise ValueError(f"source {self.name}: unknown categories {unknown}; known: {sorted(scraper.CATEGORIES)}")
        original = scraper.CATEGORIES
        scraper.CATEGORIES = {k: v for k, v in original.items() if k in wanted}
        opts = SimpleNamespace(
            page_timeout_ms=int(self.o.get("page_timeout_ms", 90000)), scrape_attempts=int(self.o.get("scrape_attempts", 3)),
            max_scrolls=int(self.o.get("max_scrolls", 20)), legacy_skip_items=int(self.o.get("legacy_skip_items", 25)))
        try:
            products, ok = scraper.fetch_all_products(opts)
            link = next(iter(scraper.CATEGORIES.values())) if len(scraper.CATEGORIES) == 1 else ""
        finally:
            scraper.CATEGORIES = original
        self.raw_count = len(products)
        if not products:
            raise RuntimeError("Hamrahtel returned zero products (site unreachable, blocked, or page layout changed)")
        if not ok:
            import logging
            logging.getLogger("pricecompare").warning("hamrahtel: at least one category failed after retries")
        seen, out = {}, []
        for p in products:
            base = f"{p.brand}|{p.model}|{p.color}"
            seen[base] = seen.get(base, 0) + 1
            # stable id (does NOT contain the price, unlike the old adapter, so history/overrides survive price changes)
            oid = base if seen[base] == 1 else f"{base}#{seen[base]}"
            out.append({"id": oid, "title": " ".join(x for x in (p.brand, p.model) if x), "price": p.price,
                        "stock": "in_stock",          # the quick-checkout list only shows purchasable items
                        "url": link, "color": p.color, "brand": p.brand})
        return out
