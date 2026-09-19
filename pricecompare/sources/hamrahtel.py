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
        self.catalog_titles = [" ".join(x for x in (p.brand, p.model) if x) for p in products][:3000]
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


def debug_lines(raw_lines, n=120, context=15):
    """Numbered slice of the rendered page text around the first price line (to learn the real card layout)."""
    scraper = _scraper()
    first = next((i for i, x in enumerate(raw_lines) if scraper.is_price(x)), 0)
    a = max(0, first - context)
    return [f"{i:4d} | {x}" for i, x in enumerate(raw_lines[a:a + n], start=a)]


def dump_page(category="mobile", lines=120, timeout_ms=90000, max_scrolls=20):
    """Diagnostics: print what the site really renders (text lines + JSON responses that contain prices)."""
    scraper = _scraper()
    from playwright.sync_api import sync_playwright
    url = scraper.CATEGORIES[category]
    out, json_hits = [], []
    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True)
        page = browser.new_page()

        def on_response(resp):
            try:
                if "json" in (resp.headers.get("content-type") or ""):
                    body = resp.text()
                    n = body.lower().count("price")
                    if n:
                        json_hits.append((n, len(body), resp.url[:140]))
            except Exception:
                pass
        page.on("response", on_response)
        page.goto(url, wait_until="domcontentloaded", timeout=timeout_ms)
        page.wait_for_timeout(5000)
        scraper.scroll_page(page, max_scrolls)
        body = page.locator("body").inner_text(timeout=15000)
        card_counts = {}
        for sel in ('[data-testid*="product"]', '[class*="product-card"]', '[class*="ProductCard"]', '[class*="product-item"]'):
            try:
                card_counts[sel] = page.locator(sel).count()
            except Exception:
                card_counts[sel] = "error"
        browser.close()
    raw = [c for c in (scraper.clean_text(x) for x in body.splitlines()) if c]
    out.append(f"URL: {url}")
    out.append(f"non-empty text lines: {len(raw)} | price-like lines: {sum(scraper.is_price(x) for x in raw)}")
    out.append(f"card selector counts: {card_counts}")
    out.append("JSON responses containing 'price' (count, bytes, url): " + str(sorted(json_hits, reverse=True)[:6]))
    out.append("--- rendered text around the first price line ---")
    out += debug_lines(raw, lines)
    parsed = scraper.parse_body_lines(raw)
    out.append(f"--- parse_body_lines(): {len(parsed)} products; first 12 ---")
    out += [f"   {p}" for p in parsed[:12]]
    return "\n".join(out)
