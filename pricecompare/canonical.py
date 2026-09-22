"""Canonical identity helpers shared by discovery, reporting and future sources."""
from __future__ import annotations
import re


def _clean_token(value) -> str:
    return re.sub(r"[^a-z0-9]+", "", str(value or "").lower())


def strong_identifier(offer):
    """Return a cross-source identifier only for EAN/GTIN-like fields.

    Store-local SKU/product_id values are intentionally ignored: they are not
    comparable across merchants.
    """
    extra = getattr(offer, "extra", {}) or {}
    for key in ("gtin", "ean", "ean13", "ean8", "barcode", "upc"):
        value = extra.get(key)
        if value is None:
            continue
        digits = re.sub(r"\D", "", str(value))
        if len(digits) in (8, 12, 13, 14) and digits.strip("0"):
            return digits.zfill(14)
    return ""


def product_key(offer) -> str:
    """Canonical product identity; source is never part of the key.

    Colour deliberately belongs to the variant key, not the product key.
    """
    parts = [offer.brand, *sorted(set(offer.model_core)), *sorted(set(offer.tiers))]
    if offer.network:
        parts.append(offer.network)
    if offer.storage_gb is not None:
        parts.append(f"{offer.storage_gb}gb")
    if offer.ram_gb is not None:
        parts.append(f"ram{offer.ram_gb}")
    if offer.region:
        parts.append(offer.region)
    if offer.condition:
        parts.append(offer.condition)
    return _slug(parts)


def product_key_from_watch(watch, attrs=None) -> str:
    core = list(getattr(attrs, "core", []) or [])
    tiers = list(getattr(attrs, "tiers", []) or [])
    parts = [watch.brand, *sorted(set(core)), *sorted(set(tiers))]
    network = getattr(attrs, "network", "") if attrs else ""
    if network:
        parts.append(network)
    if watch.storage_gb is not None:
        parts.append(f"{watch.storage_gb}gb")
    if watch.ram_gb is not None:
        parts.append(f"ram{watch.ram_gb}")
    if watch.region:
        parts.append(watch.region)
    if watch.condition:
        parts.append(watch.condition)
    return _slug(parts)


def variant_key(offer, unknown_color="unknown") -> str:
    return _slug([product_key(offer), offer.color or unknown_color])


def _slug(parts) -> str:
    return re.sub(r"[^a-z0-9]+", "_", "_".join(str(x) for x in parts if x not in (None, ""))).strip("_")
