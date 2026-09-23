"""ExonTel phone catalog source.

ExonTel's category is rendered dynamically, while the product page exposes the
actual colour/price/stock choices.  The source therefore uses one Playwright
session to discover product URLs, then parses each product page into ordinary
Source records.  No matching logic lives here; all identity decisions remain
in the central extractor/matcher/discovery pipeline.
"""
from __future__ import annotations

import json
import re
from urllib.parse import urljoin

from bs4 import BeautifulSoup

from .base import Source


_FA_DIGITS = str.maketrans("۰۱۲۳۴۵۶۷۸۹٠١٢٣٤٥٦٧٨٩", "01234567890123456789")
_PRICE_RE = re.compile(r"^[\d۰-۹٠-٩][\d۰-۹٠-٩.,٬،٫]*\s*(?:تومان|تومن|ریال|rial|toman)?$", re.I)
_STOCK_IN = {"موجود", "موجود است", "available", "in stock", "instock"}
_STOCK_OUT = {"ناموجود", "ناموجود است", "out of stock", "unavailable", "sold out"}


def _clean(v) -> str:
    return re.sub(r"\s+", " ", str(v or "").replace("\u200c", " ").strip())


def _price_text(v):
    s = _clean(v)
    if not s:
        return None
    return s if _PRICE_RE.match(s) else None


def _stock(v):
    s = _clean(v).lower()
    if s in _STOCK_IN:
        return "in_stock"
    if s in _STOCK_OUT:
        return "out_of_stock"
    return None


def _jsonld(soup):
    for node in soup.select('script[type="application/ld+json"]'):
        try:
            data = json.loads(node.string or node.get_text())
        except Exception:
            continue
        values = data if isinstance(data, list) else [data]
        for item in values:
            if isinstance(item, dict):
                yield item
                if isinstance(item.get("@graph"), list):
                    yield from (x for x in item["@graph"] if isinstance(x, dict))


def _meta(soup, prop):
    node = soup.select_one(f'meta[property="{prop}"], meta[name="{prop}"]')
    return _clean(node.get("content")) if node else ""


def _variant_rows(body_lines):
    """Parse ExonTel's visible 'انتخاب و سفارش' variant block.

    Current live pages expose each choice as: colour -> price/ناموجود -> add-to-cart.
    The parser deliberately accepts English equivalents too and never invents a
    colour when the page does not expose one.
    """
    lines = [_clean(x) for x in body_lines if _clean(x)]
    try:
        start = next(i for i, x in enumerate(lines) if x in {"انتخاب و سفارش", "Choose and order"}) + 1
    except StopIteration:
        return []
    end = next((i for i in range(start, len(lines)) if lines[i] in {"توضیحات محصول", "Product description"}), len(lines))
    rows = []
    i = start
    while i < end:
        color = lines[i]
        if color in {"افزودن به سبد", "Add to cart"} or re.fullmatch(r"\d+\s+تنوع", color):
            i += 1
            continue
        if i + 1 < end:
            price = _price_text(lines[i + 1])
            stock = _stock(lines[i + 1])
            if price or stock:
                rows.append((color, lines[i + 1], price, stock))
                i += 2
                if i < end and lines[i] in {"افزودن به سبد", "Add to cart"}:
                    i += 1
                continue
        i += 1
    return rows


def parse_product_html(html: str, url: str = "") -> list[dict]:
    """Parse one real ExonTel product page into standard Source records."""
    soup = BeautifulSoup(html, "lxml")
    title = _clean(soup.select_one("h1").get_text(" ", strip=True) if soup.select_one("h1") else "")
    if not title:
        # fallback to product JSON-LD / og:title
        title = next((_clean(x.get("name")) for x in _jsonld(soup) if x.get("@type") in ("Product", ["Product"]) and x.get("name")), "")
    if not title:
        title = _meta(soup, "og:title")
    if not title:
        return []

    product_id = ""
    m = re.search(r"/product/([^/?#]+)", url)
    if m:
        product_id = m.group(1)

    image = _meta(soup, "og:image")
    brand = ""
    sku = gtin = ""
    base_price = None
    base_stock = None
    for ld in _jsonld(soup):
        if ld.get("@type") == "Product":
            b = ld.get("brand")
            brand = _clean(b.get("name") if isinstance(b, dict) else b) or brand
            sku = _clean(ld.get("sku")) or sku
            gtin = _clean(ld.get("gtin") or ld.get("gtin13") or ld.get("gtin14")) or gtin
            image = _clean((ld.get("image") or [image])[0] if isinstance(ld.get("image"), list) else (ld.get("image") or image))
            offers = ld.get("offers") or {}
            if isinstance(offers, dict):
                base_price = offers.get("price") or base_price
                av = str(offers.get("availability") or "").lower()
                base_stock = "in_stock" if "instock" in av else ("out_of_stock" if "outofstock" in av else base_stock)

    lines = [_clean(x) for x in soup.get_text("\n", strip=True).splitlines() if _clean(x)]
    variants = _variant_rows(lines)

    # If the visible variant block exists, emit one Offer per concrete colour.
    if variants:
        out = []
        for idx, (raw_color, marker, price, stock) in enumerate(variants, 1):
            out.append({
                "id": f"{product_id}:v{idx}" if product_id else f"{title}:v{idx}",
                "title": title,
                "price": price if price is not None else base_price,
                "stock": stock or base_stock,
                "url": url,
                "image": image,
                "color": raw_color,
                "brand": brand,
                "extra": {"product_id": product_id or None, "sku": sku or None, "gtin": gtin or None,
                          "variant_marker": marker},
            })
        return out

    # Product has no visible colour choices: keep colour unknown rather than
    # guessing from the title.  The central matcher treats unknown != known.
    visible_price = next((_price_text(x) for x in lines if _price_text(x)), None)
    visible_stock = next((_stock(x) for x in lines if _stock(x)), None)
    return [{
        "id": product_id or sku or title,
        "title": title,
        "price": visible_price or base_price,
        "stock": visible_stock or base_stock,
        "url": url,
        "image": image,
        "color": "",
        "brand": brand,
        "extra": {"product_id": product_id or None, "sku": sku or None, "gtin": gtin or None},
    }]


def _category_links(html: str, base_url: str) -> list[str]:
    soup = BeautifulSoup(html, "lxml")
    out = []
    for a in soup.select('a[href*="/product/"]'):
        href = a.get("href")
        if href:
            out.append(urljoin(base_url, href))
    return list(dict.fromkeys(out))


def _playwright():
    try:
        from playwright.sync_api import sync_playwright
        return sync_playwright
    except ImportError as exc:  # pragma: no cover - environment specific
        raise RuntimeError("ExonTel needs Playwright: pip install playwright && playwright install chromium") from exc


class ExontelSource(Source):
    type_name = "exontel"

    def _fixture_records(self, locations):
        out, seen = [], set()
        for loc in locations:
            html = self.read(loc)
            soup = BeautifulSoup(html, "lxml")
            blocks = soup.select("[data-exontel-product]")
            if not blocks:
                blocks = [soup]
            for block in blocks:
                url = block.get("data-url") or self.o.get("base_url", "https://exontel.com/")
                for r in parse_product_html(str(block), url):
                    key = (str(r.get("id")), r.get("color", ""))
                    if key not in seen:
                        seen.add(key); out.append(r)
        return out

    def records(self, watchlist):
        # A local path is intentionally supported for deterministic parser tests.
        if self.o.get("path"):
            records = self._fixture_records(self.locations(watchlist))
            if not records:
                raise RuntimeError("ExonTel fixture returned zero products")
            self.raw_count = len(records)
            self.catalog_titles = list(dict.fromkeys(r["title"] for r in records if r.get("title")))
            self.note = f"fixture/parser; {self.raw_count} product-variant records"
            return records

        url = self.o.get("url") or "https://exontel.com/category/phones?available=true"
        base_url = self.o.get("base_url", "https://exontel.com/")
        max_products = int(self.o.get("max_products", 1000))
        max_scrolls = int(self.o.get("max_scrolls", 30))
        stable_scrolls = int(self.o.get("stable_scrolls", 3))
        timeout_ms = int(self.o.get("page_timeout_ms", 90000))

        sync_playwright = _playwright()
        links = []
        pages = [url]
        with sync_playwright() as pw:
            browser = pw.chromium.launch(headless=True)
            context = browser.new_context()
            page = context.new_page()
            for cat_url in pages:
                page.goto(cat_url, wait_until="domcontentloaded", timeout=timeout_ms)
                try:
                    page.wait_for_load_state("networkidle", timeout=min(timeout_ms, 15000))
                except Exception:
                    pass
                stable = 0
                previous = 0
                for _ in range(max_scrolls):
                    links = list(dict.fromkeys(links + _category_links(page.content(), base_url)))
                    # Also collect explicit pagination links when present.
                    for href in page.locator('a[href*="page="]').evaluate_all("els => els.map(e => e.href)"):
                        if href not in pages:
                            pages.append(href)
                    if len(links) >= max_products:
                        break
                    page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
                    page.wait_for_timeout(800)
                    # Common load-more controls; click only visible/enabled buttons.
                    clicked = False
                    for text in ("مشاهده بیشتر", "بارگذاری بیشتر", "Load more", "Show more"):
                        loc = page.get_by_text(text, exact=True)
                        if loc.count() and loc.first.is_visible() and loc.first.is_enabled():
                            try:
                                loc.first.click(timeout=1500); clicked = True; page.wait_for_timeout(1000)
                            except Exception:
                                pass
                    if len(links) == previous and not clicked:
                        stable += 1
                    else:
                        stable = 0
                    previous = len(links)
                    if stable >= stable_scrolls:
                        break

            links = links[:max_products]
            records, seen = [], set()
            for link in links:
                try:
                    page.goto(link, wait_until="domcontentloaded", timeout=timeout_ms)
                    try:
                        page.wait_for_load_state("networkidle", timeout=min(timeout_ms, 10000))
                    except Exception:
                        pass
                    for r in parse_product_html(page.content(), page.url):
                        key = (str(r.get("id")), r.get("color", ""))
                        if key in seen:
                            continue
                        seen.add(key); records.append(r)
                except Exception:
                    # One changed/broken product page must not kill the whole source.
                    continue
            browser.close()

        if not records:
            raise RuntimeError("ExonTel returned zero products (site unreachable, blocked, or layout changed)")
        self.raw_count = len(records)
        self.catalog_titles = list(dict.fromkeys(r["title"] for r in records if r.get("title")))
        self.note = f"Playwright category discovery + product pages; {len(links)} product URLs, {len(records)} offers"
        return records
