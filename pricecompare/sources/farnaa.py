"""Farnaa mobile catalog source.

The mobile category page embeds the full catalog in
``window.productAnalyticsData``.  That structured payload is preferred over
brittle price-card selectors because it contains stable product ids, prices,
availability and variants.  The rendered product cards are used to enrich the
same records with product URLs, images and visible colour names.
"""
from __future__ import annotations

import json
import re
from urllib.parse import urljoin

from bs4 import BeautifulSoup

from .base import Source


_ANALYTICS_MARKER = "Object.assign(window.productAnalyticsData,"


def _json_object_after_marker(html: str) -> dict:
    """Extract the JSON object passed to Object.assign(...).

    ``json.JSONDecoder.raw_decode`` is used instead of a greedy regex so
    embedded strings/braces cannot accidentally truncate the object.
    """
    pos = html.find(_ANALYTICS_MARKER)
    if pos < 0:
        raise ValueError("Farnaa productAnalyticsData was not found")
    start = html.find("{", pos + len(_ANALYTICS_MARKER))
    if start < 0:
        raise ValueError("Farnaa productAnalyticsData has no JSON object")
    payload, _ = json.JSONDecoder().raw_decode(html[start:])
    if not isinstance(payload, dict):
        raise ValueError("Farnaa productAnalyticsData is not an object")
    return payload


def _clean(value) -> str:
    return str(value or "").strip()


def _product_cards(html: str, base_url: str) -> dict:
    """Return DOM metadata keyed by Farnaa's stable data-product-id."""
    soup = BeautifulSoup(html, "lxml")
    out = {}
    for card in soup.select(".item-product[data-product-id]"):
        pid = _clean(card.get("data-product-id"))
        if not pid:
            continue
        link = card.select_one("a.hover-img-link[href], .title-box a[href]")
        img = card.select_one("img[data-src], img[src]")
        title_el = card.select_one(".title-box a")
        colors = [
            _clean(x.get_text(" ", strip=True))
            for x in card.select(".wz-matrix-tooltip-text")
            if _clean(x.get_text(" ", strip=True))
        ]
        out[pid] = {
            "url": urljoin(base_url, link.get("href")) if link and link.get("href") else "",
            "image": urljoin(base_url, img.get("data-src") or img.get("src")) if img else "",
            "title": _clean(title_el.get_text(" ", strip=True)) if title_el else "",
            "colors": colors,
        }
    return out


def parse_farnaa_html(html: str, base_url: str = "https://farnaa.com/") -> list:
    """Parse a Farnaa mobile category snapshot into Source record dictionaries."""
    analytics = _json_object_after_marker(html)
    cards = _product_cards(html, base_url)
    records = []

    for pid, item in analytics.items():
        if not isinstance(item, dict):
            continue
        pid = _clean(item.get("item_id") or pid)
        title = _clean(item.get("item_name"))
        if not pid or not title:
            continue

        variants = item.get("variants") or []
        if not isinstance(variants, list):
            variants = []

        # A product with no concrete variant is still useful for stock/catalog
        # diagnostics. Its zero price is deliberately represented as None.
        if not variants:
            availability = _clean(item.get("availability")).lower()
            price = item.get("price")
            price = None if not price or float(price) <= 0 else price
            records.append({
                "id": pid,
                "title": title,
                "price": price,
                "stock": availability,
                "url": cards.get(pid, {}).get("url", ""),
                "image": cards.get(pid, {}).get("image", ""),
                "color": _clean(item.get("item_color")),
                "brand": _clean(item.get("item_brand")),
                "extra": {"product_id": pid, "guarantee": _clean(item.get("item_guarantee"))},
            })
            continue

        for index, variant in enumerate(variants):
            if not isinstance(variant, dict):
                continue
            vid = _clean(variant.get("variant_id")) or f"{pid}:v{index + 1}"
            price = variant.get("price", item.get("price"))
            price = None if price is None or float(price) <= 0 else price
            color = _clean(variant.get("item_color")) or _clean(item.get("item_color"))
            availability = _clean(variant.get("availability")) or _clean(item.get("availability"))
            records.append({
                "id": f"{pid}:{vid}",
                "title": title,
                "price": price,
                "stock": availability,
                "url": cards.get(pid, {}).get("url", ""),
                "image": cards.get(pid, {}).get("image", ""),
                "color": color,
                "brand": _clean(item.get("item_brand")),
                "extra": {
                    "product_id": pid,
                    "variant_id": vid,
                    "guarantee": _clean(variant.get("item_guarantee") or item.get("item_guarantee")),
                    "seller": _clean(variant.get("item_seller") or item.get("item_seller")),
                },
            })
    return records


class FarnaaSource(Source):
    type_name = "farnaa"

    def records(self, watchlist):
        locations = self.locations(watchlist)
        all_records = []
        seen = set()
        self.catalog_titles = []

        for loc in locations:
            html = self.read(loc)
            records = parse_farnaa_html(html, self.o.get("base_url", "https://farnaa.com/"))
            for record in records:
                key = str(record.get("id") or "")
                if key and key not in seen:
                    seen.add(key)
                    all_records.append(record)
            if not all_records:
                raise RuntimeError("Farnaa returned zero products")

        self.raw_count = len(all_records)
        self.catalog_titles = [r["title"] for r in all_records if r.get("title")]
        self.note = f"analytics catalog + DOM enrichment; {self.raw_count} product/variant records"
        return all_records
