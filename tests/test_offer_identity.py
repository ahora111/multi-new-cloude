from datetime import datetime, timezone

from pricecompare.config import load_discovery, load_overrides, load_settings, load_sources, load_watchlist
from pricecompare.runner import run
from pricecompare.models import Offer

ROOT = __import__("pathlib").Path(__file__).resolve().parents[1]


def test_pipeline_collapses_duplicate_source_offer_ids():
    """The central pipeline must never expose two Offers with the same source/id."""
    from pricecompare.runner import dedupe_offers

    offers = [
        Offer("x", "p1", "Test Phone", 100, "toman", url="https://x/p1"),
        Offer("x", "p1", "Test Phone", 100, "toman", url="https://x/p1", image="https://x/i.jpg", raw_color="black"),
        Offer("x", "p2", "Test Phone", 101, "toman", url="https://x/p2"),
        Offer("y", "p1", "Test Phone", 99, "toman", url="https://y/p1"),
    ]
    out = dedupe_offers(offers)
    assert {(o.source, o.source_offer_id) for o in out} == {("x", "p1"), ("x", "p2"), ("y", "p1")}
    assert next(o for o in out if o.source == "x" and o.source_offer_id == "p1").image.endswith("i.jpg")
