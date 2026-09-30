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


_GENERIC_TITLES = {
    "رنگ بندی و بهترین پیشنهاد", "رنگ‌بندی و بهترین پیشنهاد", "بهترین پیشنهاد",
    "رنگ بندی", "رنگ‌بندی", "محصولات", "محصولات موجود", "دسته بندی", "دسته‌بندی",
    "فیلتر", "مرتب سازی", "مرتب‌سازی", "جستجو", "search", "products", "product",
}


def _clean_title(value: str) -> str:
    value = re.sub(r"\s+", " ", str(value or "")).strip(" -|:")
    return value


def _looks_like_product_title(title: str, url: str = "") -> bool:
    """Reject navigation/filter/UI labels that can accidentally carry prices.

    Kasra Plus exposes a number of recommendation/filter blocks containing price
    values but no product identity. Those must never become Offers.
    """
    t = _clean_title(title)
    if not t or len(t) < 3 or len(t) > 300:
        return False
    norm = re.sub(r"[\u200c\u200f\u200e]+", "", t).lower()
    if norm in {re.sub(r"[\u200c\u200f\u200e]+", "", x).lower() for x in _GENERIC_TITLES}:
        return False
    generic_tokens = ("رنگ بندی", "رنگ‌بندی", "بهترین پیشنهاد", "فیلتر محصولات", "مرتب سازی", "مرتب‌سازی")
    if any(x in norm for x in generic_tokens):
        return False
    # A real product URL is strong evidence even for a short Persian title.
    if "/product/" in (url or "").lower():
        return True
    # Otherwise require at least a model-like signal (digit or common mobile brand).
    brands = ("samsung", "galaxy", "xiaomi", "redmi", "poco", "apple", "iphone",
              "honor", "huawei", "nokia", "motorola", "tecno", "infinix", "oppo",
              "oneplus", "realme", "tcl", "glx", "vivo", "hanofer", "generalluxe",
              "جنرال لوکس", "سامسونگ", "شیائومی", "اپل", "آیفون", "نوکیا", "آنر")
    return bool(re.search(r"\d", norm) or any(b in norm for b in brands))


def _product_link_fallback(soup, base_url):
    """Extract cards by their real /product/ link when CSS classes are opaque."""
    rows = []
    seen = set()
    for link in soup.select("a[href*='/product/']"):
        href = link.get("href") or ""
        url = _abs(base_url, href)
        title = _clean_title(_text(link) or _first_attr(link, ("title", "aria-label")))
        if not _looks_like_product_title(title, url):
            continue
        # Find the nearest compact ancestor containing an actual price.
        node = link
        for _ in range(8):
            node = getattr(node, "parent", None)
            if not node or not getattr(node, "name", None):
                break
            text = _text(node)
            if len(text) > 1000:
                continue
            price, price_raw = _price(node)
            if price is None:
                continue
            pid = _first_attr(node, ("data-product-id", "data-product_id", "data-id", "data-sku", "data-code"))
            sku = _first_attr(node, ("data-sku", "data-product-sku", "data-code"))
            pid = sku or pid or _url_id(url) or _canonical_url(url) or _stable_id(url)
            color = _first_attr(node, ("data-color", "data-colour")) or _text(node.select_one(".color, .colour, .product-color, [itemprop=color]"))
            brand = _first_attr(node, ("data-brand", "data-brand-name")) or _text(node.select_one(".brand, .product-brand, [itemprop=brand]"))
            stock = _first_attr(node, ("data-stock", "data-availability")) or _stock(text)
            key = (pid, str(price_raw), color)
            if key not in seen:
                seen.add(key)
                rows.append({"id": pid, "title": title, "price": price_raw, "stock": stock, "url": url,
                             "image": _image(node, base_url), "color": color, "brand": brand,
                             "storage": _first_attr(node, ("data-storage", "data-capacity")),
                             "ram": _first_attr(node, ("data-ram", "data-memory")),
                             "extra": {"sku": sku or None, "old_price": None},
                             "currency_detected": _currency_from_text(text)})
            break
    return rows


def _title(node):
    for sel in ("[itemprop='name']", "h1", "h2", "h3", "h4", ".product-title", ".product-name", ".title", "[class*='product'][class*='title']"):
        el = node.select_one(sel)
        if el:
            t = _text(el)
            if t and len(t) <= 300:
                return _clean_title(t)
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
    """Find product-like objects in JSON/embedded app state.

    Supports both direct prices and Schema.org JSON-LD where the price lives
    under ``offers`` / ``aggregateOffer``.
    """
    out = []
    def walk(x, parent=None):
        if isinstance(x, dict):
            keys = {str(k).lower() for k in x}
            has_title = bool(x.get("name") or x.get("title") or x.get("product_name") or x.get("productName"))
            price_keys = {"price", "sale_price", "saleprice", "final_price", "finalprice", "selling_price", "sellingprice"}
            if has_title and (keys & price_keys):
                out.append(x)
            # JSON-LD Product commonly stores price in offers.
            if has_title:
                for offer_key in ("offers", "offer", "aggregateOffer", "aggregate_offer"):
                    offers = x.get(offer_key)
                    if isinstance(offers, dict):
                        merged = dict(x)
                        merged.update(offers)
                        if any(merged.get(k) not in (None, "") for k in price_keys):
                            out.append(merged)
                    elif isinstance(offers, list):
                        for offer in offers:
                            if isinstance(offer, dict):
                                merged = dict(x); merged.update(offer)
                                if any(merged.get(k) not in (None, "") for k in price_keys):
                                    out.append(merged)
            for v in x.values():
                walk(v, x)
        elif isinstance(x, list):
            for v in x:
                walk(v, parent)
    walk(value)
    return out

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
    if not _looks_like_product_title(title, str(pick("url", "link", "product_url", "productUrl") or fallback_url)):
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
    json_records = []

    # JSON-LD / application state is collected secondarily.
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
                json_records.append(rec)

    # DOM product cards. Generic selectors are deliberately conservative: a node is accepted only if it has a title and price.
    for node in _product_nodes(soup):
        title = _title(node)
        price, price_raw = _price(node)
        if not title or price is None:
            continue
        link = node.select_one("a[href]")
        url = _abs(base_url, link.get("href")) if link else ""
        if not _looks_like_product_title(title, url):
            continue
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

    records.extend(json_records)

    # Generic fallback for JS-rendered sites whose card classes are opaque.
    # Find small containers containing both a product-like link/title and a price.
    existing_nodes = {id(n) for n in _product_nodes(soup)}
    for price_el in soup.select("[itemprop='price'], [data-price], [data-sale-price], meta[itemprop='price'], span, div, p, strong, b"):
        raw = price_el.get("content") if price_el.name == "meta" else (_first_attr(price_el, ("data-sale-price", "data-price")) or _text(price_el))
        cls = " ".join(price_el.get("class") or []).lower() if getattr(price_el, "get", None) else ""
        has_price_signal = (
            "تومان" in raw or "ریال" in raw or _PRICE_WORDS.search(raw)
            or "price" in cls or "cost" in cls or price_el.get("data-price") or price_el.get("data-sale-price")
        )
        if not raw or not has_price_signal or parse_price(raw) is None:
            continue
        container = price_el
        for _ in range(6):
            container = getattr(container, "parent", None)
            if not container or not getattr(container, "name", None):
                break
            if id(container) in existing_nodes:
                break
            if len(_text(container)) > 900:
                continue
            link = container.select_one("a[href*='/product/']") or container.select_one("a[href]")
            title = ""
            if link:
                title = _clean_title(_text(link) or _first_attr(link, ("title", "aria-label")))
            if not title:
                title = _title(container)
            if title and link and _looks_like_product_title(title, _abs(base_url, link.get("href") or "")) and id(container) not in existing_nodes:
                href = link.get("href") or ""
                url = _abs(base_url, href)
                pid = _first_attr(container, ("data-product-id", "data-product_id", "data-id", "data-sku", "data-code"))
                sku = _first_attr(container, ("data-sku", "data-product-sku", "data-code"))
                pid = sku or pid or _url_id(url) or _canonical_url(url) or _stable_id(url)
                stock = _first_attr(container, ("data-stock", "data-availability")) or _stock(_text(container))
                records.append({"id": pid, "title": title, "price": raw, "stock": stock, "url": url,
                                "image": _image(container, base_url), "color": _first_attr(container, ("data-color", "data-colour")),
                                "brand": _first_attr(container, ("data-brand", "data-brand-name")),
                                "storage": _first_attr(container, ("data-storage", "data-capacity")),
                                "ram": _first_attr(container, ("data-ram", "data-memory")),
                                "extra": {"sku": sku or None, "old_price": None},
                                "currency_detected": _currency_from_text(_text(container))})
                break

    # Final, high-confidence path: real product links + nearest price-bearing card.
    records.extend(_product_link_fallback(soup, base_url))

    return _dedupe(records)


def _dedupe(records):
    out, seen = [], set()
    for r in records:
        if not r.get("title") or r.get("price") in (None, ""):
            continue
        variant = "|".join(str(r.get(k) or "") for k in ("color", "storage", "ram"))
        rid = str(r.get("id") or "")
        sku = str((r.get("extra") or {}).get("sku") or "")
        if sku:
            key = ("sku", sku)
        elif rid:
            key = ("id", rid, variant)
        else:
            key = ("fallback", str(r.get("title") or ""), str(r.get("price") or ""), _canonical_url(r.get("url") or ""))
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



def _proxy_product_records(body: str, base_url: str):
    """Parse product links/prices returned by a text/HTML fetch proxy.

    GitHub-hosted runners can fail DNS resolution for the Iranian Kasra domain even
    though the site is reachable elsewhere.  A proxy response may be either HTML or
    Markdown/plain text, so keep this parser deliberately conservative: only links
    whose path contains /product/ are considered product identities, and a nearby
    explicit currency/price is required.
    """
    if not body:
        return []
    # If the proxy returned HTML, reuse the normal parser first.
    try:
        rows = parse_kasrapars_html(body, base_url)
        if rows:
            return rows
    except Exception:
        pass

    lines = [re.sub(r"\s+", " ", x).strip() for x in body.splitlines()]
    lines = [x for x in lines if x]
    out = []
    link_re = re.compile(r"(?:\[[^\]]+\]\()?((?:https?:)?//[^)\s]+/product/[^)\s]+)", re.I)
    for i, line in enumerate(lines):
        m = link_re.search(line)
        if not m:
            continue
        url = m.group(1).rstrip('.,)')
        # Markdown link text is the strongest title signal.
        title = ""
        lm = re.search(r"\[([^\]]+)\]\(", line)
        if lm:
            title = _clean_title(lm.group(1))
        if not title:
            title = _clean_title(re.sub(r"https?://[^\s]+", "", line))
        if not _looks_like_product_title(title, url):
            continue
        nearby = []
        for j in range(max(0, i - 3), min(len(lines), i + 6)):
            txt = lines[j]
            if not ("تومان" in txt or "ریال" in txt or re.search(r"\b(?:toman|rial)\b", txt, re.I)):
                continue
            val = parse_price(txt)
            if val is not None and val > 0:
                nearby.append((j, val, txt))
        if not nearby:
            continue
        _, price, price_text = min(nearby, key=lambda x: abs(x[0] - i))
        out.append({
            "id": _url_id(url) or _stable_id(url),
            "title": title,
            "price": price,
            "url": url,
            "stock": _stock(" ".join(lines[max(0, i - 2):min(len(lines), i + 6)])),
            "currency_detected": _currency_from_text(price_text),
            "extra": {"proxy_fallback": True},
        })
    return _dedupe(out)



_TELEGRAM_MOBILE_HINTS = (
    "samsung", "galaxy", "xiaomi", "redmi", "poco", "iphone", "apple",
    "honor", "huawei", "nokia", "motorola", "tecno", "infinix", "oppo",
    "oneplus", "realme", "tcl", "glx", "vivo", "hanofer", "generalluxe",
    "جنرال لوکس", "سامسونگ", "شیائومی", "ردمی", "پوکو", "اپل", "آیفون",
    "آنر", "هواوی", "نوکیا", "موتورولا", "تکنو", "اینفینیکس", "اوپو",
    "وان پلاس", "ریلمی", "نوکیا", "گوشی موبایل", "گوشی موبايل", "گوشی",
)
_TELEGRAM_NON_MOBILE_HINTS = (
    "airpods", "buds", "powerbank", "پاوربانک", "هندزفری", "هدفون",
    "شارژر", "کابل", "watch", "ساعت هوشمند", "speaker", "اسپیکر",
    "soundcore", "party box", "qcy", "mouse", "کیبورد", "کنسول",
)

def _telegram_mobile_title(title: str) -> bool:
    t = _clean_title(title).lower()
    if not _looks_like_product_title(t, ""):
        return False
    if any(x in t for x in _TELEGRAM_NON_MOBILE_HINTS):
        return False
    return any(x in t for x in _TELEGRAM_MOBILE_HINTS) or bool(
        re.search(r"\b(?:a\d{2,3}|s\d{2,3}|note\s*\d+|redmi\s+[a-z]?\d+|iphone\s*\d+)\b", t, re.I)
    )

def _telegram_product_records(body: str, base_url: str):
    """Extract mobile price offers from Telegram HTML *or* Markdown/plain text.

    This is a degraded fallback only: Telegram posts are a promotional subset of
    the catalog, not a replacement for the live Kasra Plus catalog.
    """
    if not body:
        return []

    # Telegram preview can arrive as normal HTML, while read proxies such as Jina
    # commonly return Markdown. Support both forms so a CI runner does not depend
    # on one particular transport.
    soup = BeautifulSoup(body, "html.parser")
    blocks = soup.select("div.tgme_widget_message_wrap") or soup.select("div.tgme_widget_message")
    if blocks:
        chunks = []
        for block in blocks:
            text_node = block.select_one(".tgme_widget_message_text")
            if not text_node:
                continue
            chunks.append((
                text_node.get_text("\n", strip=True),
                [(a.get_text(" ", strip=True), a.get("href") or "") for a in text_node.select("a[href]")],
            ))
        return _telegram_text_records(chunks, base_url)

    # Markdown/plain text fallback. Keep each paragraph/post separated where
    # possible, but also support proxies that flatten the channel into one block.
    text = soup.get_text("\n", strip=True) if soup.find() else body
    return _telegram_text_records([(text, [])], base_url)


def _telegram_text_records(chunks, base_url):
    out = []
    for raw_text, anchors in chunks:
        lines = [re.sub(r"\s+", " ", x).strip() for x in str(raw_text or "").splitlines()]
        lines = [x for x in lines if x]
        if not lines:
            continue

        product_links = [(_clean_title(label), href) for label, href in anchors
                         if "/product/" in (href or "").lower()]

        # Markdown link syntax may survive a read proxy even when there are no HTML anchors.
        for idx, line in enumerate(lines):
            for lm in re.finditer(r"\[([^\]]+)\]\((https?://[^)]+/product/[^)]+)\)", line, re.I):
                product_links.append((_clean_title(lm.group(1)), lm.group(2)))
            lines[idx] = re.sub(r"\[([^\]]+)\]\((https?://[^)]+)\)", r"\1", line)

        for i, line in enumerate(lines):
            has_currency = ("تومان" in line or "ریال" in line or
                            re.search(r"\b(?:toman|rial)\b", line, re.I))
            # Kasra Telegram commonly formats prices as 83/459/000 without a currency unit.
            normalized_digits = str(line).translate(str.maketrans(
                "۰۱۲۳۴۵۶۷۸۹٠١٢٣٤٥٦٧٨٩", "01234567890123456789"))
            numeric_only = re.sub(r"[^0-9.,٬،٫/]", "", normalized_digits)
            looks_like_price = (
                bool(re.search(r"\d{1,3}(?:[\d.,٬،٫/]{3,})", numeric_only))
                and len(re.sub(r"\D", "", numeric_only)) >= 6
            )
            if not (has_currency or looks_like_price):
                continue
            price = parse_price(line)
            if price is None or price <= 0:
                continue

            # Find the closest preceding mobile-looking title, stopping at a new
            # promo/header boundary. This handles both Telegram HTML and flattened Markdown.
            candidates = []
            for j in range(max(0, i - 6), i):
                candidate = re.sub(r"^[^\w\u0600-\u06ff]+", "", lines[j]).strip(" -:|*_")
                candidate = re.sub(r"^(?:قیمت(?:\s+ویژه)?|price)\s*[:：-]?\s*", "", candidate, flags=re.I)
                if not candidate:
                    continue
                low = candidate.lower()
                if any(x in low for x in _TELEGRAM_NON_MOBILE_HINTS):
                    # An accessory between the phone title and this price is a hard
                    # boundary. Do not let the price of Buds/AirPods/etc. attach to
                    # the previous phone title.
                    candidates = []
                    break
                if any(x in low for x in ("کسری پلاس", "بهترین قیمت", "ارسال سریع", "امکان خرید", "۳۰ دقیقه", "30 دقیقه")):
                    continue
                if _telegram_mobile_title(candidate):
                    candidates.append(candidate)
            title = candidates[-1] if candidates else ""

            url = ""
            if product_links:
                if title:
                    for label, href in product_links:
                        if label and (label in title or title in label):
                            url = href
                            break
                if not url:
                    # Only attach a product link if its label itself looks mobile-like;
                    # never attach an unrelated accessory URL to a phone price.
                    for label, href in reversed(product_links):
                        if _telegram_mobile_title(label):
                            url = href
                            if not title:
                                title = label
                            break

            if not title or not _telegram_mobile_title(title):
                continue
            url = urljoin(base_url, url) if url else ""
            pid = _url_id(url) if url else ""
            if not pid:
                pid = "tg_" + hashlib.sha1((title + "|" + str(price)).encode("utf-8")).hexdigest()
            out.append({
                "id": pid,
                "title": title,
                "price": price,
                "url": url,
                "stock": "in_stock",
                "currency_detected": _currency_from_text(line) or "toman",
                "extra": {"telegram_fallback": True},
            })
    return _dedupe(out)

def _proxy_urls(url: str):
    from urllib.parse import quote
    encoded = quote(url, safe="")
    # Jina is generally good at reaching sites that are DNS/geo inaccessible from CI.
    # AllOrigins is retained as a second independent fallback for raw HTML.
    return [
        f"https://r.jina.ai/http://{urlsplit(url).netloc}{urlsplit(url).path}"
        + (f"?{urlsplit(url).query}" if urlsplit(url).query else ""),
        f"https://r.jina.ai/{url}",
        f"https://api.allorigins.win/raw?url={encoded}",
    ]

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
                        "json" in ctype or "javascript" in ctype or any(token in url.lower() for token in (
                            "/api/", "graphql", "ajax", "search", "product", "products", "catalog", "shop", "query", "filter"
                        ))
                    )
                    if not interesting:
                        return
                    # Do not cap responses before inspecting them. Modern catalog pages
                    # can issue many asset/search requests before the actual product API.
                    if len(response_urls) < 500:
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
                        page.wait_for_timeout(int(self.o.get("browser_initial_wait_ms", 3000)))

                        # Parse whatever was rendered as a secondary path.
                        rows = parse_kasrapars_html(page.content(), initial)
                        records.extend(rows)

                        stable = 0
                        last_height = 0
                        for _ in range(max_scrolls):
                            height = page.evaluate("document.body.scrollHeight")
                            page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
                            page.wait_for_timeout(int(self.o.get("browser_scroll_wait_ms", 1200)))
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


    def _telegram_fallback(self):
        """Read Kasra's public Telegram channel as the primary catalog transport.

        GitHub-hosted runners can be unable to resolve/reach plus.kasrapars.ir while
        Telegram's public preview remains reachable.  We therefore treat Telegram
        as a first-class source transport, not merely an emergency fallback.
        """
        import requests
        from urllib.parse import quote, urlsplit, parse_qs

        channel_url = str(self.o.get("telegram_fallback_url", "https://t.me/s/kasrapars")).strip()
        timeout = int(self.o.get("telegram_fallback_timeout", 30))
        max_pages = max(1, int(self.o.get("telegram_max_pages", 8)))
        candidates = []
        base_candidates = [
            channel_url,
            "https://www.t.me/s/kasrapars",
            "https://telegram.me/s/kasrapars",
        ]
        # Direct Telegram first. Read proxies are transport fallbacks only.
        for u in base_candidates:
            if u not in candidates:
                candidates.append(u)
        for u in list(base_candidates[:1]):
            candidates.extend([
                f"https://r.jina.ai/http://{urlsplit(u).netloc}{urlsplit(u).path}",
                f"https://r.jina.ai/{u}",
                f"https://api.allorigins.win/raw?url={quote(u, safe='')}",
            ])

        tried = []
        rows = []
        seen_ids = set()
        next_before = None

        def parse_page(body, page_url):
            parsed = _telegram_product_records(body, self.o.get("base_url", "https://plus.kasrapars.ir/"))
            # The HTML preview exposes data-post="kasrapars/<message_id>".  The
            # smallest ID lets us walk backwards through older price-list posts.
            ids = []
            for m in re.finditer(r'data-post=["\']kasrapars/(\d+)', body or "", re.I):
                try:
                    ids.append(int(m.group(1)))
                except Exception:
                    pass
            return parsed, (min(ids) if ids else None)

        def request_url(u):
            r = requests.get(u, timeout=timeout, headers={
                "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/154 Safari/537.36",
                "Accept": "text/html,application/xhtml+xml,text/plain,text/markdown;q=0.9,*/*;q=0.8",
            }, allow_redirects=True)
            return r

        # Try direct/proxy HTTP transports and paginate backwards when the preview
        # exposes message IDs. A single promotional page is not enough for a catalog.
        working_base = None
        for transport in candidates:
            try:
                r = request_url(transport)
                tried.append(f"{transport}={r.status_code}")
                if r.status_code != 200 or not r.text:
                    continue
                page_rows, min_id = parse_page(r.text, transport)
                if page_rows:
                    rows.extend(page_rows)
                    working_base = transport
                    next_before = min_id
                    break
            except Exception as exc:
                tried.append(f"{transport}=ERR:{type(exc).__name__}")

        # Continue pagination on the same working transport where possible.
        if working_base and next_before:
            for _ in range(max_pages - 1):
                if not next_before or next_before <= 1:
                    break
                sep = "&" if "?" in working_base else "?"
                page_url = f"{working_base}{sep}before={next_before}"
                try:
                    r = request_url(page_url)
                    tried.append(f"{page_url}={r.status_code}")
                    if r.status_code != 200 or not r.text:
                        break
                    page_rows, min_id = parse_page(r.text, page_url)
                    rows.extend(page_rows)
                    if not min_id or min_id >= next_before:
                        break
                    next_before = min_id
                except Exception:
                    break

        rows = _dedupe(rows)
        if rows:
            return rows, 200, f"{working_base or channel_url};pages~{max_pages}"

        # Last resort: render Telegram preview in Chromium. This is deliberately
        # separate from the Kasra-site browser fallback.
        try:
            from playwright.sync_api import sync_playwright
            with sync_playwright() as pw:
                browser = pw.chromium.launch(headless=True)
                context = browser.new_context(viewport={"width": 1440, "height": 1200}, locale="fa-IR")
                page = context.new_page()
                page.goto(channel_url, wait_until="domcontentloaded", timeout=timeout * 1000)
                try:
                    page.wait_for_load_state("networkidle", timeout=10000)
                except Exception:
                    pass
                page.wait_for_timeout(1500)
                body = page.content()
                page_rows, min_id = parse_page(body, channel_url)
                rows.extend(page_rows)
                # Browser pagination through ?before= is useful when requests is blocked.
                for _ in range(max_pages - 1):
                    if not min_id or min_id <= 1:
                        break
                    u = f"{channel_url}{'&' if '?' in channel_url else '?'}before={min_id}"
                    try:
                        page.goto(u, wait_until="domcontentloaded", timeout=timeout * 1000)
                        page.wait_for_timeout(800)
                        body = page.content()
                        page_rows, new_min = parse_page(body, u)
                        rows.extend(page_rows)
                        if not new_min or new_min >= min_id:
                            break
                        min_id = new_min
                    except Exception:
                        break
                context.close()
                browser.close()
        except Exception as exc:
            tried.append(f"playwright=ERR:{type(exc).__name__}")

        rows = _dedupe(rows)
        return rows, (200 if rows else 0), ";".join(tried)

    def _proxy_fallback(self, locations):
        """Fetch through public read proxies when CI cannot resolve Kasra DNS."""
        import requests
        rows = []
        tried = set()
        timeout = int(self.o.get("proxy_timeout", 45))
        for initial in locations:
            for proxy in _proxy_urls(initial):
                if proxy in tried:
                    continue
                tried.add(proxy)
                try:
                    r = requests.get(proxy, timeout=timeout, headers={"User-Agent": "Mozilla/5.0"})
                    if r.status_code != 200 or not r.text:
                        continue
                    parsed = _proxy_product_records(r.text, initial)
                    if parsed:
                        rows.extend(parsed)
                except Exception:
                    continue
        return _dedupe(rows), len(tried)

    def records(self, watchlist):
        locations = self.locations(watchlist)

        # Telegram-first architecture: Kasra's public channel is the reliable
        # transport from CI when the Iranian website is DNS/geo inaccessible.
        # The normal site/browser/proxy paths remain available as enrichment and
        # fallback transports.
        if bool(self.o.get("telegram_first", False)) and bool(self.o.get("telegram_fallback", True)):
            tg_rows, tg_status, tg_url = self._telegram_fallback()
            if tg_rows:
                detected_units = {r.get("currency_detected") for r in tg_rows if r.get("currency_detected")}
                self.raw_count = len(tg_rows)
                self.catalog_titles = list(dict.fromkeys(r["title"] for r in tg_rows if r.get("title")))
                self.note = (f"telegram-first; telegram_status={tg_status}; telegram_rows={len(tg_rows)}; "
                             f"telegram_source={tg_url}; degraded_catalog=true")
                return tg_rows
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

        if not out and bool(self.o.get("proxy_fallback", True)):
            proxy_rows, proxy_attempts = self._proxy_fallback(locations)
            out = _dedupe(out + proxy_rows)
            if out:
                detected_units.update(r.get("currency_detected") for r in out if r.get("currency_detected"))
                self.raw_count = len(out)
                self.catalog_titles = list(dict.fromkeys(r["title"] for r in out if r.get("title")))
                self.note = (f"http+browser+proxy; pages={pages}; proxy_attempts={proxy_attempts}; "
                             f"detected_currency={','.join(sorted(detected_units)) or 'unknown'}")
                return out
            self.note = f"http+browser+proxy-empty; pages={pages}; proxy_attempts={proxy_attempts}"

        if not out and bool(self.o.get("telegram_fallback", True)):
            tg_rows, tg_status, tg_url = self._telegram_fallback()
            out = _dedupe(out + tg_rows)
            if out:
                detected_units.update(r.get("currency_detected") for r in out if r.get("currency_detected"))
                self.raw_count = len(out)
                self.catalog_titles = list(dict.fromkeys(r["title"] for r in out if r.get("title")))
                self.note = (f"http+browser+proxy+telegram; pages={pages}; "
                             f"telegram_status={tg_status}; telegram_rows={len(tg_rows)}; "
                             f"degraded_catalog=true")
                return out
            self.note = (f"http+browser+proxy+telegram-empty; pages={pages}; "
                         f"telegram_status={tg_status}; telegram_url={tg_url}")

        if not out:
            raise RuntimeError("KasraPars returned zero products (HTTP, browser/API, proxy and Telegram fallbacks found none)")
        self.raw_count = len(out)
        self.catalog_titles = list(dict.fromkeys(r["title"] for r in out if r.get("title")))
        self.note = f"http+html/json; pages={pages}; detected_currency={','.join(sorted(detected_units)) or 'unknown'}"
        return out

