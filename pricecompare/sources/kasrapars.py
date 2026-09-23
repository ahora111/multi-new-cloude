"""KasraPars (Kasra Plus) mobile catalog source.

The source intentionally keeps site-specific parsing here and sends plain records to the
normal Source contract.  Matching, colour/brand canonicalisation and pricing stay in the
central pipeline.
"""
from __future__ import annotations

import hashlib
import json
import re
from urllib.parse import parse_qsl, urlencode, urljoin, urlsplit, urlunsplit

from bs4 import BeautifulSoup

from .base import Source
from ..extract import parse_price


_PRICE_WORDS = re.compile(r"(?:قیمت|price|sale|فروش|تخفیف|discount)", re.I)
_IN_STOCK = ("موجود", "موجود در انبار", "آماده ارسال", "available", "in stock", "instock", "ready to ship")
_OUT_STOCK = ("ناموجود", "اتمام موجودی", "تمام شد", "sold out", "out of stock", "unavailable", "به زودی", "به‌زودی")


def _text(node) -> str:
    return node.get_text(" ", strip=True) if node else ""


def _first_attr(node, names):
    for name in names:
        value = node.get(name)
        if value not in (None, ""):
            return str(value).strip()
    return ""


def _abs(base_url, value):
    return urljoin(base_url, str(value).strip()) if value else ""


def _canonical_url(url: str) -> str:
    if not url:
        return ""
    p = urlsplit(url)
    return urlunsplit((p.scheme.lower(), p.netloc.lower(), p.path.rstrip("/") or "/", "", ""))


def _url_id(url: str) -> str:
    path = urlsplit(url).path.rstrip("/")
    if not path:
        return ""
    value = path.rsplit("/", 1)[-1]
    return value if value else ""


def _stable_id(url: str) -> str:
    return "urlsha1_" + hashlib.sha1(_canonical_url(url).encode("utf-8")).hexdigest()


def _image(node, base_url):
    if not node:
        return ""
    candidates = []
    for sel in ("[itemprop='image']", "img"):
        for img in node.select(sel):
            for attr in ("src", "data-src", "data-lazy-src", "data-original"):
                v = img.get(attr)
                if v:
                    candidates.append(_abs(base_url, v))
            srcset = img.get("srcset") or img.get("data-srcset")
            if srcset:
                candidates.append(_abs(base_url, srcset.split(",")[0].strip().rsplit(" ", 1)[0]))
    for v in candidates:
        low = v.lower()
        if any(x in low for x in ("logo", "favicon", "sprite", "placeholder")):
            continue
        return v
    return ""


def _stock(text: str):
    t = re.sub(r"\s+", " ", text or "").strip().lower()
    if any(x.lower() in t for x in _OUT_STOCK):
        return "out_of_stock"
    if any(x.lower() in t for x in _IN_STOCK):
        return "in_stock"
    return None


def _price_candidates(node):
    if not node:
        return []
    sels = (
        "[itemprop='price']", "meta[itemprop='price']", "[data-sale-price]", "[data-price]",
        ".sale-price", ".special-price", ".final-price", ".current-price", ".discount-price",
        ".price", ".product-price", "[class*='sale'][class*='price']", "[class*='current'][class*='price']",
    )
    out = []
    for sel in sels:
        for el in node.select(sel):
            value = el.get("content") if el.name == "meta" else (_first_attr(el, ("data-sale-price", "data-price")) or _text(el))
            if value:
                p = parse_price(value)
                if p is not None and p > 0:
                    out.append((p, value, sel))
    # Last resort: look at short text chunks containing price words or currency units.
    for el in node.select("span,div,p,strong,b"):
        txt = _text(el)
        if len(txt) <= 120 and ("تومان" in txt or "ریال" in txt or _PRICE_WORDS.search(txt)):
            p = parse_price(txt)
            if p is not None and p > 0:
                out.append((p, txt, "text"))
    return out


def _price(node):
    """Prefer explicit sale/current price; never choose a struck old price when a sale price exists."""
    if not node:
        return None, ""
    explicit = _price_candidates(node)
    if not explicit:
        return None, ""
    # Selector order above already puts current/sale fields before generic .price.
    return explicit[0][0], explicit[0][1]


def _currency_from_text(text: str) -> str:
    if "ریال" in (text or "") or re.search(r"\brial\b", text or "", re.I):
        return "rial"
    if "تومان" in (text or "") or re.search(r"\btoman\b", text or "", re.I):
        return "toman"
    return ""


def _field(node, labels):
    if not node:
        return ""
    text = _text(node)
    for label in labels:
        m = re.search(rf"{re.escape(label)}\s*[:：\-]?\s*([^|\n]+)", text, re.I)
        if m:
            value = m.group(1).strip()
            if value:
                return value[:100]
    return ""


def _title(node):
    for sel in ("[itemprop='name']", "h1", "h2", "h3", "h4", ".product-title", ".product-name", ".title", "[class*='product'][class*='title']"):
        el = node.select_one(sel)
        if el:
            t = _text(el)
            if t and len(t) <= 300:
                return t
    return ""


def _product_nodes(soup):
    selectors = (
        "[data-product-id]", "[data-product_id]", "[data-product]", "[data-sku]",
        "article.product", "li.product", ".product-item", ".product-card", ".product_box",
        ".product-box", ".item-product", ".product-list-item", "[itemtype*='Product']",
    )
    seen = set()
    nodes = []
    for sel in selectors:
        for n in soup.select(sel):
            marker = id(n)
            if marker not in seen:
                seen.add(marker); nodes.append(n)
    return nodes


def _json_products(value):
    """Find product-like objects in JSON/embedded app state without assuming a framework."""
    out = []
    def walk(x):
        if isinstance(x, dict):
            keys = {str(k).lower() for k in x}
            if ("name" in keys or "title" in keys) and ({"price", "sale_price", "saleprice", "final_price", "finalprice", "selling_price", "sellingprice"} & keys):
                out.append(x)
            for v in x.values():
                walk(v)
        elif isinstance(x, list):
            for v in x:
                walk(v)
    walk(value)
    return out


def _json_record(obj, base_url, fallback_url=""):
    def pick(*keys):
        for k in keys:
            if obj.get(k) not in (None, ""):
                return obj.get(k)
        return ""
    title = str(pick("name", "title", "product_name", "productName") or "").strip()
    if not title:
        return None
    url = _abs(base_url, pick("url", "link", "product_url", "productUrl") or fallback_url)
    pid = str(pick("id", "product_id", "productId", "sku", "code") or "").strip()
    sku = str(pick("sku", "SKU") or "").strip()
    # Offer identity is variant-level. Prefer SKU/variant id when available so two
    # colour/SKU variants of one product cannot collapse into one Offer later.
    gtin = str(pick("gtin", "ean", "ean13", "barcode", "upc") or "").strip()
    price = pick("sale_price", "salePrice", "final_price", "finalPrice", "selling_price", "sellingPrice", "price")
    old = pick("old_price", "oldPrice", "regular_price", "regularPrice", "compare_at_price", "compareAtPrice")
    stock = pick("stock", "availability", "available", "is_available", "isAvailable")
    color = pick("color", "colour")
    brand = pick("brand", "brand_name", "brandName")
    image = pick("image", "image_url", "imageUrl", "thumbnail")
    raw = " ".join(str(x) for x in (title, price, stock) if x not in (None, ""))
    unit = _currency_from_text(raw)
    if sku:
        pid = sku
    elif not pid:
        pid = _url_id(url) or _canonical_url(url) or _stable_id(url)
    extra = {"sku": sku or None, "gtin": gtin or None, "old_price": parse_price(old) if old else None}
    variant = pick("variant_id", "variantId", "combination_id", "combinationId")
    if variant:
        extra["variant_id"] = str(variant)
    return {"id": pid, "title": title, "price": price, "stock": stock, "url": url, "image": _abs(base_url, image),
            "color": color, "brand": brand, "storage": pick("storage", "capacity", "storage_gb", "storageGb"),
            "ram": pick("ram", "ram_gb", "ramGb"), "extra": extra, "currency_detected": unit}



def _json_response_records(payload, base_url):
    """Extract offer-like records from API JSON, including nested variant objects.

    Kasra Plus may expose products through a client-side API rather than rendering
    product cards in the initial HTML.  API payloads often keep the product title
    on a parent object and price/color/SKU on a nested variant, so this helper
    carries useful parent fields into variant dictionaries without changing the
    normal source contract.
    """
    records = []
    def walk(value, parent=None):
        if isinstance(value, dict):
            parent = parent or {}
            inherited = {}
            for key in ("name", "title", "product_name", "productName", "url", "link", "product_url", "productUrl", "brand", "brand_name", "brandName", "image", "image_url", "imageUrl", "thumbnail"):
                if value.get(key) not in (None, ""):
                    inherited[key] = value[key]
            merged = dict(parent)
            merged.update(inherited)
            # A variant/offer may have the price while the parent carries title.
            if (merged.get("name") or merged.get("title")) and any(value.get(k) not in (None, "") for k in (
                "price", "sale_price", "salePrice", "final_price", "finalPrice", "selling_price", "sellingPrice"
            )):
                candidate = dict(merged)
                candidate.update(value)
                rec = _json_record(candidate, base_url)
                if rec:
                    records.append(rec)
            for v in value.values():
                if isinstance(v, (dict, list)):
                    walk(v, merged)
        elif isinstance(value, list):
            for v in value:
                walk(v, parent)
    walk(payload)
    return _dedupe(records)

def parse_kasrapars_html(html: str, base_url: str) -> list:
    soup = BeautifulSoup(html, "lxml")
    records = []

    # JSON-LD / application state is preferred when present because it usually has real IDs/SKU/GTIN.
    blobs = []
    for script in soup.select("script[type='application/ld+json'], script#__NEXT_DATA__, script[type='application/json']"):
        txt = script.string or script.get_text()
        if not txt.strip():
            continue
        try:
            blobs.append(json.loads(txt))
        except Exception:
            continue
    for blob in blobs:
        for obj in _json_products(blob):
            rec = _json_record(obj, base_url)
            if rec:
                records.append(rec)

    # DOM product cards. Generic selectors are deliberately conservative: a node is accepted only if it has a title and price.
    for node in _product_nodes(soup):
        title = _title(node)
        price, price_raw = _price(node)
        if not title or price is None:
            continue
        link = node.select_one("a[href]")
        url = _abs(base_url, link.get("href")) if link else ""
        pid = _first_attr(node, ("data-product-id", "data-product_id", "data-id", "data-sku", "data-code"))
        sku = _first_attr(node, ("data-sku", "data-product-sku", "data-code"))
        # A product card may share data-product-id across colour variants; SKU is the
        # stable Offer identity when it exists.
        if sku:
            pid = sku
        brand = _first_attr(node, ("data-brand", "data-brand-name")) or _text(node.select_one(".brand, .product-brand, [itemprop=brand]")) or _field(node, ("brand", "برند"))
        color = _first_attr(node, ("data-color", "data-colour")) or _text(node.select_one(".color, .colour, .product-color, [itemprop=color]")) or _field(node, ("color", "colour", "رنگ"))
        storage = _first_attr(node, ("data-storage", "data-capacity")) or _text(node.select_one(".storage, .capacity, .product-storage")) or _field(node, ("storage", "capacity", "حافظه", "ظرفیت"))
        ram = _first_attr(node, ("data-ram", "data-memory")) or _text(node.select_one(".ram, .memory, .product-ram")) or _field(node, ("ram", "memory", "رم"))
        stock = _first_attr(node, ("data-stock", "data-availability")) or _stock(_text(node))
        if not pid:
            pid = _url_id(url) or _canonical_url(url) or _stable_id(url)
        extra = {"sku": sku or None, "old_price": None}
        old = _price_candidates(node)
        # Keep a metadata old price when a del/old/regular field is present.
        for sel in ("del", ".old-price", ".regular-price", ".old-price-value", ".before-price", "[data-old-price]"):
            el = node.select_one(sel)
            if el:
                extra["old_price"] = parse_price(el.get("content") or el.get("data-old-price") or _text(el))
                break
        unit = _currency_from_text(_text(node))
        records.append({"id": pid, "title": title, "price": price_raw, "stock": stock, "url": url,
                        "image": _image(node, base_url), "color": color, "brand": brand,
                        "storage": storage, "ram": ram, "extra": extra, "currency_detected": unit})

    return _dedupe(records)


def _dedupe(records):
    out, seen = [], set()
    for r in records:
        if not r.get("title") or r.get("price") in (None, ""):
            continue
        variant = "|".join(str(r.get(k) or "") for k in ("color", "storage", "ram"))
        key = (str(r.get("id") or ""), variant, _canonical_url(r.get("url") or ""))
        if key in seen:
            continue
        seen.add(key); out.append(r)
    return out


def _next_url(html, current_url):
    soup = BeautifulSoup(html, "lxml")
    link = soup.select_one("link[rel='next'][href], a[rel='next'][href]")
    if link:
        return _abs(current_url, link.get("href"))
    for a in soup.select("a[href]"):
        txt = _text(a).lower()
        aria = (a.get("aria-label") or "").lower()
        if txt in {"بعدی", "next", ">", "›", "→"} or "next" in aria or "بعد" in aria:
            return _abs(current_url, a.get("href"))
    return ""


def _page_url(url, page, param="page"):
    parts = urlsplit(url)
    q = dict(parse_qsl(parts.query, keep_blank_values=True))
    q[param] = str(page)
    return urlunsplit((parts.scheme, parts.netloc, parts.path, urlencode(q), ""))


class KasraParsSource(Source):
    type_name = "kasrapars"

    def _browser_fallback(self, locations, max_scrolls=12):
        """Use Chromium as a second-stage extractor and capture client-side API JSON.

        The previous fallback only parsed rendered HTML. If the site renders its
        catalog from XHR/fetch, the DOM can contain no product cards at all.
        Intercepting JSON responses lets us parse the actual catalog payload.
        """
        try:
            from playwright.sync_api import sync_playwright
        except Exception as exc:
            raise RuntimeError("Playwright is required for KasraPars browser fallback") from exc

        records, visited = [], set()
        api_hits = 0
        response_urls = []
        with sync_playwright() as pw:
            browser = pw.chromium.launch(headless=True)
            context = browser.new_context(viewport={"width": 1440, "height": 1000}, locale="fa-IR")
            page = context.new_page()

            def on_response(response):
                nonlocal api_hits
                try:
                    ctype = (response.headers.get("content-type") or "").lower()
                    url = response.url
                    interesting = (
                        "json" in ctype or any(token in url.lower() for token in (
                            "/api/", "graphql", "ajax", "search", "product", "products", "catalog", "shop"
                        ))
                    )
                    if not interesting or len(response_urls) >= 80:
                        return
                    response_urls.append(url)
                    body = response.text()
                    if not body or len(body) > 15_000_000:
                        return
                    try:
                        payload = json.loads(body)
                    except Exception:
                        return
                    rows = _json_response_records(payload, url)
                    if rows:
                        api_hits += 1
                        records.extend(rows)
                except Exception:
                    # A single failed/opaque browser response must not abort the scrape.
                    return

            page.on("response", on_response)
            try:
                for initial in locations:
                    try:
                        page.goto(initial, wait_until="domcontentloaded", timeout=int(self.o.get("page_timeout_ms", 90000)))
                        try:
                            page.wait_for_load_state("networkidle", timeout=15000)
                        except Exception:
                            pass
                        page.wait_for_timeout(1800)

                        # Parse whatever was rendered as a secondary path.
                        rows = parse_kasrapars_html(page.content(), initial)
                        records.extend(rows)

                        stable = 0
                        last_height = 0
                        for _ in range(max_scrolls):
                            height = page.evaluate("document.body.scrollHeight")
                            page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
                            page.wait_for_timeout(900)
                            if height == last_height:
                                stable += 1
                            else:
                                stable = 0
                            last_height = height
                            if stable >= 2:
                                break
                        rows = parse_kasrapars_html(page.content(), initial)
                        records.extend(rows)

                        # Follow obvious next-page links when the site uses normal pagination.
                        links = page.locator("a[href]").all()
                        for link in links:
                            try:
                                href = link.get_attribute("href") or ""
                                txt = (link.inner_text() or "").strip().lower()
                                aria = (link.get_attribute("aria-label") or "").lower()
                                if href and (txt in {"بعدی", "next", ">", "›", "→"} or "next" in aria or "بعد" in aria):
                                    u = urljoin(initial, href)
                                    if u not in visited:
                                        visited.add(u)
                                        page.goto(u, wait_until="domcontentloaded", timeout=int(self.o.get("page_timeout_ms", 90000)))
                                        try:
                                            page.wait_for_load_state("networkidle", timeout=10000)
                                        except Exception:
                                            pass
                                        page.wait_for_timeout(1200)
                                        records.extend(parse_kasrapars_html(page.content(), u))
                                    break
                            except Exception:
                                continue
                    except Exception:
                        continue
            finally:
                context.close()
                browser.close()
        return _dedupe(records), api_hits, response_urls

    def records(self, watchlist):
        locations = self.locations(watchlist)
        max_pages = int(self.o.get("max_pages", 100))
        pagination_param = str(self.o.get("pagination_param", "page"))
        follow_next = bool(self.o.get("follow_next", True))
        all_records, seen_pages = [], set()
        pages = 0
        detected_units = set()
        try:
            for initial in locations:
                current = initial
                while current and current not in seen_pages and pages < max_pages:
                    seen_pages.add(current); pages += 1
                    body = self.read(current)
                    stripped = body.lstrip()
                    if stripped.startswith("{") or stripped.startswith("["):
                        try:
                            payload = json.loads(body)
                        except json.JSONDecodeError:
                            payload = None
                        rows = _json_response_records(payload, current) if payload is not None else []
                    else:
                        rows = parse_kasrapars_html(body, current)
                    all_records.extend(rows)
                    detected_units.update(r.get("currency_detected") for r in rows if r.get("currency_detected"))

                    nxt = _next_url(body, current) if follow_next else ""
                    if not nxt and rows and pages < max_pages and self.o.get("page_query_fallback", False) and urlsplit(current).scheme:
                        candidate = _page_url(current, pages + 1, pagination_param)
                        nxt = candidate if candidate not in seen_pages else ""
                    if not rows:
                        break
                    current = nxt
        finally:
            session = getattr(self.http, "session", None)
            if session is not None and hasattr(session, "close"):
                session.close()

        out = _dedupe(all_records)
        if not out and bool(self.o.get("browser_fallback", False)):
            browser_rows, api_hits, api_urls = self._browser_fallback(
                locations, int(self.o.get("browser_max_scrolls", 12))
            )
            out = _dedupe(out + browser_rows)
            if out:
                detected_units.update(r.get("currency_detected") for r in out if r.get("currency_detected"))
                self.raw_count = len(out)
                self.catalog_titles = list(dict.fromkeys(r["title"] for r in out if r.get("title")))
                self.note = (f"http+browser-api; pages={pages}; api_hits={api_hits}; "
                             f"api_urls={len(api_urls)}; detected_currency={','.join(sorted(detected_units)) or 'unknown'}")
                return out
            self.note = f"http+browser-empty; pages={pages}; api_hits={api_hits}; api_urls={len(api_urls)}"

        if not out:
            raise RuntimeError("KasraPars returned zero products (HTTP parser and browser/API fallback both found none)")
        self.raw_count = len(out)
        self.catalog_titles = list(dict.fromkeys(r["title"] for r in out if r.get("title")))
        self.note = f"http+html/json; pages={pages}; detected_currency={','.join(sorted(detected_units)) or 'unknown'}"
        return out

