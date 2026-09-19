from datetime import datetime, timedelta, timezone
from pricecompare.config import Settings
from pricecompare.models import Offer, WatchItem, IN_STOCK, OUT_OF_STOCK
from pricecompare.pricing import choose_variant, build_product, scale_check

NOW = datetime(2026, 9, 19, 12, 0, tzinfo=timezone.utc)


def off(source, price, stock=IN_STOCK, oid=None, age_min=0, color="black"):
    o = Offer(source, oid or source, "t", price, "toman", stock=stock,
              fetched_at=(NOW - timedelta(minutes=age_min)).isoformat())
    o.price_toman, o.color = price, color
    return o


def pick(offers, settings=None, prio=None, degraded=(), max_price=None):
    return choose_variant(offers, prio or {}, settings or Settings(), NOW, set(degraded), max_price)[0]


def test_lowest_valid_price_wins_and_is_explained():
    r = pick([off("a", 100), off("b", 90), off("c", 95)])
    assert r["winner"]["source"] == "b" and r["runner_up"]["source"] == "c"
    assert r["savings"]["amount_toman"] == 5 and "ارزان‌ترین" in r["why"]


def test_out_of_stock_stale_and_invalid_are_excluded_with_reason():
    r = pick([off("a", 50, OUT_OF_STOCK), off("b", 60, age_min=999), off("c", 0), off("d", 70)])
    assert r["winner"]["source"] == "d"
    reasons = {o["source"]: o["excluded_reason"] for o in r["offers"]}
    assert reasons["a"] and reasons["b"] and reasons["c"] and reasons["d"] is None


def test_low_outlier_cannot_win_and_high_outlier_ignored():
    r = pick([off("a", 45_000_000), off("b", 44_000_000), off("c", 450_000), off("d", 900_000_000)])
    assert r["winner"]["source"] == "b"
    assert {o["source"] for o in r["offers"] if o["suspect"]} == {"c", "d"}


def test_outlier_ratio_setting_is_used():
    offers = [off("a", 100), off("b", 105), off("c", 60)]
    assert pick(offers, Settings(outlier_ratio=3.0))["winner"]["source"] == "c"
    assert pick(offers, Settings(outlier_ratio=1.5))["winner"]["source"] == "a"


def test_two_offers_huge_gap_flagged_for_review_not_silently_trusted():
    r = pick([off("a", 64_000_000), off("b", 640_000_000)])
    assert r["needs_review"] and all(o["suspect"] for o in r["offers"])


def test_tie_broken_by_source_priority():
    r = pick([off("a", 100), off("b", 100)], prio={"a": 20, "b": 10})
    assert r["winner"]["source"] == "b" and "تساوی" in r["why"]


def test_max_age_setting_is_used():
    o = [off("a", 50, age_min=100), off("b", 60)]
    assert pick(o, Settings(max_price_age_minutes=180))["winner"]["source"] == "a"
    assert pick(o, Settings(max_price_age_minutes=30))["winner"]["source"] == "b"


def test_degraded_source_never_wins():
    r = pick([off("a", 50), off("b", 60)], degraded={"a"})
    assert r["winner"]["source"] == "b"


def test_no_valid_offer_and_max_price_warning():
    assert pick([off("a", 50, OUT_OF_STOCK)])["winner"] is None
    assert any("سقف" in w for w in pick([off("a", 500)], max_price=100)["warnings"])


def test_colours_never_compete_and_mixed_region_is_flagged():
    w = WatchItem(id="w", brand="x", model="m")
    a, b, c = off("a", 100, color="black"), off("b", 50, color="blue"), off("c", 120, color="black")
    a.region, c.region = "cha", "vietnam"
    p = build_product(w, [(a, None), (b, None), (c, None)], {}, Settings(), NOW, set())
    prices = {v["variant"]: v["winner"]["price_toman"] for v in p["variants"]}
    assert prices == {"black": 100, "blue": 50}
    black = next(v for v in p["variants"] if v["variant"] == "black")
    assert black["needs_review"] and any("ریجن" in x for x in black["warnings"])


def test_requested_colours_filter():
    w = WatchItem(id="w", brand="x", model="m", colors=["blue"])
    p = build_product(w, [(off("a", 100, color="black"), None), (off("b", 50, color="blue"), None)], {}, Settings(), NOW, set())
    assert [v["variant"] for v in p["variants"]] == ["blue"] and p["ignored_offers"]


def test_scale_check_detects_ten_x_gap():
    w = WatchItem(id="w", brand="x", model="m")
    offs = []
    for i, col in enumerate(["black", "blue", "gray", "red"]):
        offs += [(off("a", 10_000_000 + i, color=col), None), (off("b", 100_000_000 + i, color=col), None)]
    p = build_product(w, offs, {}, Settings(outlier_ratio=100), NOW, set())
    warns = scale_check([p], Settings())
    assert warns and "ریال/تومان" in warns[0]
    assert all(v["needs_review"] for v in p["variants"])
