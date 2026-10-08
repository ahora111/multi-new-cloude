"""Digikala B2B (b2b.digikala.com) mobile catalog source.

b2b.digikala.com is a Next.js SPA: the HTML shell contains no product data.
The catalog is served by the portal's own JSON API, which is public (no login):

  Listing:  GET https://b2b.digikala.com/api/v1/products?category_id=3&page=1&sort=price-desc
  Details:  GET https://b2b.digikala.com/api/v1/products/pdp/{product_id}

Listing rows carry id / name / short_title / price / base_image / colors[] but
NO stock flag. Empirically (verified against PDP payloads, 2026-10-03):

* a sold-out product is listed with ``price == 0`` and an empty ``colors`` list,
  and its PDP has ``in_stock: false`` with an empty ``variants`` array;
* an in-stock product always has a positive price and at least one colour.

The PDP payload has ``in_stock`` plus per-variant colour, price, warranty and
``remaining_stock`` (null = no explicit limit).  So ``details: all`` (default)
refines every in-stock listing row into exact per-colour offers;
``details: candidates`` refines only watchlist candidates (like Eways);
``details: none`` keeps the raw listing rows.

⚠️ API prices are RIAL (PDP ``formatted_price`` is "﷼5,199,990,000") — declare
``currency_unit: rial`` in sources.yaml; the pipeline converts to toman.

sources.yaml:
  - name: digikala_b2b
    type: digikala_b2b
    currency_unit: rial
    min_expected_products: 20
    url: https://b2b.digikala.com/api/v1/products?category_id=3&page=1&sort=price-desc
    base_url: https://b2b.digikala.com/
    max_pages: 100
    details: all              # all | candidates | none
    max_details: 800          # cap on PDP calls per run
    include_out_of_stock: false
"""
from __future__ import annotations

import json
import logging
from urllib.parse import urljoin

from ..extract import Extractor
from .base import Source

log = logging.getLogger(__name__)

LISTING_PAGE_SIZE = 12


def _https(url: str) -> str:
    """The paginator returns http:// links; the API itself lives on https."""
    if url and url.startswith("http://"):
        return "https://" + url[len("http://"):]
    return url or ""


def _product_url(pid, base_url: str) -> str:
    """SPA product route (the only pattern the portal answers with 200)."""
    return urljoin(base_url if base_url.endswith("/") else base_url + "/", f"products/product/{pid}")


def _pdp_url(pid, base_url: str) -> str:
    return urljoin(base_url if base_url.endswith("/") else base_url + "/", f"api/v1/products/pdp/{pid}")


def _image_of(item: dict) -> str:
    img = item.get("base_image") or {}
    for key in ("large_image_url", "medium_image_url", "small_image_url", "original_image_url"):
        value = str(img.get(key) or "").strip()
        if value:
            return value
    return ""


def _clean(value) -> str:
    return str(value).strip() if value is not None and str(value).strip() else ""


def parse_listing_payload(payload: dict, base_url: str = "https://b2b.digikala.com/") -> tuple:
    """Parse one /api/v1/products page -> (records, next_url).

    One record per configurable product.  The colour is only filled when the
    product has exactly ONE colour (then the listing price certainly belongs to
    it); multi-colour prices are refined per colour via the PDP payload.
    """
    data = payload.get("data") if isinstance(payload, dict) else None
    if not isinstance(data, list):
        raise ValueError("Digikala B2B listing payload has no 'data' list")

    records = []
    for item in data:
        if not isinstance(item, dict):
            continue
        pid = _clean(item.get("id"))
        title = _clean(item.get("name")) or _clean(item.get("short_title"))
        if not pid or not title:
            continue
        raw_price = item.get("price")
        price = None if raw_price is None or float(raw_price) <= 0 else raw_price
        colors = [_clean(c.get("admin_name")) for c in (item.get("colors") or []) if isinstance(c, dict)]
        colors = [c for c in colors if c]
        extra = {
            "product_id": pid,
            "short_title": _clean(item.get("short_title")),
            "listing_colors": colors,
        }
        sku = _clean(item.get("sku"))
        if sku:
            extra["sku"] = sku
        records.append({
            "id": pid,
            "title": title,
            "price": price,
            "stock": "in_stock" if price is not None else "out_of_stock",
            "url": _product_url(pid, base_url),
            "image": _image_of(item),
            "color": colors[0] if len(colors) == 1 else "",
            "storage": "", "ram": "", "brand": "",
            "extra": extra,
        })

    meta = payload.get("meta") or {}
    nxt = ""
    if isinstance(meta.get("current_page"), int) and isinstance(meta.get("last_page"), int):
        if meta["current_page"] < meta["last_page"]:
            links = payload.get("links") or {}
            nxt = _https(_clean((links.get("next") or {}).get("href") if isinstance(links.get("next"), dict) else links.get("next")))
    return records, nxt


def parse_pdp_payload(payload: dict, base_url: str = "https://b2b.digikala.com/",
                      listing_row: dict | None = None) -> list:
    """Parse one /api/v1/products/pdp/{id} payload into per-variant records.

    ``listing_row`` is the fallback template (title/image/listing price) used
    when the PDP has no usable variants.
    """
    data = payload.get("data") if isinstance(payload, dict) else None
    if not isinstance(data, dict) or not data.get("id"):
        raise ValueError("Digikala B2B PDP payload has no product 'data'")

    pid = _clean(data.get("id"))
    row = listing_row or {}
    title = _clean(data.get("name")) or _clean(data.get("short_title")) or str(row.get("title") or "")
    image = _image_of(data) or str(row.get("image") or "")
    url = _product_url(pid, base_url)
    short_title = _clean(data.get("short_title")) or str((row.get("extra") or {}).get("short_title") or "")

    variants = [v for v in (data.get("variants") or []) if isinstance(v, dict)]
    records = []

    if data.get("in_stock") and variants:
        for index, v in enumerate(variants):
            vid = _clean(v.get("id")) or f"v{index + 1}"
            raw_price = v.get("price")
            price = None if raw_price is None or float(raw_price) <= 0 else raw_price
            remaining = v.get("remaining_stock")
            try:
                sellable = remaining is None or float(remaining) > 0
            except (TypeError, ValueError):
                sellable = True
            color_info = v.get("color") or {}
            color = _clean(color_info.get("admin_name")) or _clean(color_info.get("label"))
            extra = {
                "product_id": pid,
                "variant_id": vid,
                "short_title": short_title,
            }
            sku = _clean(v.get("sku"))
            if sku:
                extra["sku"] = sku
            warranty = _clean((v.get("warranty") or {}).get("admin_name"))
            if warranty:
                extra["warranty"] = warranty
            records.append({
                "id": f"{pid}:{vid}",
                "title": title,
                "price": price,
                "stock": "in_stock" if sellable else "out_of_stock",
                "url": url,
                "image": image,
                "color": color,
                "storage": "", "ram": "", "brand": "",
                "extra": extra,
            })
        return records

    # No sellable variants: keep one diagnostic row (OOS, or in-stock without variants).
    if data.get("in_stock"):
        rec = dict(row)
        rec.update({"id": pid, "title": title, "url": url, "image": image, "stock": "in_stock"})
        rec.setdefault("price", None)
        rec.setdefault("color", "")
        rec["extra"] = dict(row.get("extra") or {}, product_id=pid, short_title=short_title)
        return [rec]

    price = data.get("price")
    price = None if price is None or float(price) <= 0 else price
    return [{
        "id": pid,
        "title": title,
        "price": price,
        "stock": "out_of_stock",
        "url": url,
        "image": image,
        "color": "",
        "storage": "", "ram": "", "brand": "",
        "extra": {"product_id": pid, "short_title": short_title},
    }]


def candidate_filter(watchlist):
    """Cheap pre-filter so PDP pages are fetched only for possible matches."""
    if not watchlist:
        return lambda name: True
    ex = Extractor()
    targets = [(w.brand, set(ex.parse(w.model).core)) for w in watchlist]

    def ok(name):
        a = ex.parse(name)
        toks = set(a.core)
        return any((not a.brand or a.brand == b) and core <= toks for b, core in targets)
    return ok


class DigikalaB2BSource(Source):
    type_name = "digikala_b2b"

    def records(self, watchlist):
        locations = self.locations(watchlist)
        base_url = str(self.o.get("base_url") or "https://b2b.digikala.com/")
        max_pages = int(self.o.get("max_pages", 100))
        follow_next = bool(self.o.get("follow_next", True))
        details_mode = str(self.o.get("details", "all")).lower()
        max_details = int(self.o.get("max_details", 800))
        include_oos = bool(self.o.get("include_out_of_stock", False))

        listing, seen, pages = [], set(), 0
        for start in locations:
            current = start
            if current.startswith(("http://", "https://")):
                log.info("digikala_b2b: fetching listing pages (max %d) ...", max_pages)
            while current and current not in seen and pages < max_pages:
                seen.add(current)
                pages += 1
                body = self.read(current)
                try:
                    payload = json.loads(body)
                except json.JSONDecodeError as exc:
                    raise RuntimeError(f"Digikala B2B listing returned invalid JSON: {exc}") from exc
                rows, nxt = parse_listing_payload(payload, base_url)
                listing.extend(rows)
                if pages == 1 or pages % 15 == 0:
                    log.info("digikala_b2b: listing page %d done (%d rows so far)", pages, len(listing))
                # only follow next links between real pages, never from a local fixture file
                current = nxt if (follow_next and current.startswith(("http://", "https://"))) else ""
        log.info("digikala_b2b: listing finished: %d pages, %d rows", pages, len(listing))
        if not listing:
            raise RuntimeError("Digikala B2B returned zero products")

        self.raw_count = len(listing)
        self.catalog_titles = [r["title"] for r in listing if r.get("title")][:3000]

        # Which products deserve a PDP refinement (exact per-colour price + stock)?
        if details_mode == "none":
            keep = {}
        elif details_mode == "candidates":
            ok = candidate_filter(watchlist)
            keep = {}
            for row in listing:
                pid = row["extra"]["product_id"]
                if row["stock"] == "in_stock" and pid not in keep and ok(row["title"]):
                    keep[pid] = True
        else:  # all
            keep = {row["extra"]["product_id"]: True for row in listing if row["stock"] == "in_stock"}
        if max_details > 0:
            keep = dict(list(keep.items())[:max_details])

        out, pdp_hits, pdp_failed = [], 0, 0
        pdp_total = len(keep)
        if pdp_total:
            log.info("digikala_b2b: refining %d in-stock products via PDP API ...", pdp_total)
        pdp_done = 0
        for row in listing:
            pid = row["extra"]["product_id"]
            refined = None
            if pid in keep:
                try:
                    payload = json.loads(self.read(_pdp_url(pid, base_url)))
                    refined = parse_pdp_payload(payload, base_url, listing_row=row)
                    pdp_hits += 1
                except Exception:                     # degrade to the listing row
                    pdp_failed += 1
                pdp_done += 1
                if pdp_done % 25 == 0 or pdp_done == pdp_total:
                    log.info("digikala_b2b: pdp %d/%d done (failed=%d)", pdp_done, pdp_total, pdp_failed)
            rows = refined or [row]
            for rec in rows:
                if include_oos or rec["stock"] != "out_of_stock":
                    out.append(rec)

        if not out:
            raise RuntimeError("Digikala B2B returned zero in-stock products "
                               "(enable include_out_of_stock to keep sold-out rows)")
        self.note = (f"api listing+{details_mode} pdp; pages={pages}; rows={self.raw_count}; "
                     f"pdp={pdp_hits}" + (f"; pdp_failed={pdp_failed}" if pdp_failed else ""))
        return out
