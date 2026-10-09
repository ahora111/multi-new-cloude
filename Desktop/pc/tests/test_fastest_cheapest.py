"""V2 §6: cheapest AND fastest vendor per colour + transparent incomplete-comparison flags."""
from datetime import datetime, time, timezone
from types import SimpleNamespace
import yaml
from conftest_helpers import make_project, load_sources_yaml
from pricecompare.config import Settings
from pricecompare.delivery import DeliveryEstimate, OrderWindow, SourceSchedule, parse_hhmm
from pricecompare.runner import attach_delivery_and_fastest, mark_incomplete, run

NOW = datetime.now(timezone.utc)


def _est(source, delivery_at, verified=True):
    return DeliveryEstimate(source=source, status="ok", delivery_at=delivery_at,
                            order_deadline=delivery_at.replace(hour=11, minute=0), verified=verified)


def _sched(delivery_hhmm: str, ship_hhmm: str = "08:00") -> SourceSchedule:
    return SourceSchedule(name="x", verified=True, windows=[OrderWindow(
        time(9, 0), time(11, 0), parse_hhmm(ship_hhmm, "s"), parse_hhmm(delivery_hhmm, "d"), 0)])


def _product(variants):
    """A minimal product dict shaped like build_product output."""
    return {"id": "p", "title": "Test Phone 256GB", "label": "Test Phone 256GB", "model": "Test Phone",
            "variants": variants}


def _variant(name, offers):
    return {"variant": name, "attributes": {"color": name}, "offers": offers, "winner": None,
            "runner_up": None, "savings": None, "why": "", "needs_review": False, "warnings": []}


def _offer(source, price):
    return {"source": source, "offer_id": f"{source}1", "title": "t", "price_toman": price,
            "valid": True, "suspect": False, "excluded_reason": None, "url": ""}


def _pick_winner(v):
    v["winner"] = min((o for o in v["offers"] if o["valid"]), key=lambda o: o["price_toman"])


def test_fastest_is_earliest_delivery_tie_broken_by_price():
    schedules = {"a": _sched("12:00"), "b": _sched("10:00"), "c": _sched("10:00")}  # ship 08:00 default
    p = _product([_variant("black", [_offer("a", 100), _offer("b", 110), _offer("c", 105)])])
    _pick_winner(p["variants"][0])
    attach_delivery_and_fastest([p], schedules, NOW, Settings())
    v = p["variants"][0]
    assert v["fastest"]["source"] == "c"            # b and c arrive together -> cheaper c wins
    assert v["winner"]["source"] == "a"             # cheapest is still a
    assert v["deltas"]["fastest_price_minus_cheapest_toman"] == 5
    assert v["delivery"]["b"]["verified"] is True


def test_cheapest_delivery_delta_when_winner_is_slower():
    schedules = {"a": _sched("18:00"), "b": _sched("10:00")}
    p = _product([_variant("black", [_offer("a", 100), _offer("b", 120)])])
    _pick_winner(p["variants"][0])
    attach_delivery_and_fastest([p], schedules, NOW, Settings())
    v = p["variants"][0]
    assert v["fastest"]["source"] == "b"
    assert v["deltas"]["cheapest_delivery_minus_fastest_hours"] == 8.0
    assert v["winner"]["delivery_label"] and "سفارش تا" in v["winner"]["delivery_label"]


def test_unknown_delivery_never_blocks_and_is_flagged():
    p = _product([_variant("black", [_offer("a", 100)])])
    _pick_winner(p["variants"][0])
    attach_delivery_and_fastest([p], {}, NOW, Settings())          # no schedules at all
    v = p["variants"][0]
    assert v["fastest"] is None and v["delivery_unknown"] is True
    assert v["winner"]["delivery_label"] == ""


def test_mark_incomplete_flags_missing_and_failed_sources():
    p = _product([_variant("black", [_offer("a", 100), _offer("b", 110),
                                     {"source": "c", "offer_id": "c1", "title": "t", "price_toman": 90,
                                      "valid": False, "suspect": False, "excluded_reason": "ناموجود"}]),
                  _variant("blue", [_offer("a", 100)])])
    mark_incomplete([p], [SimpleNamespace(name=n) for n in ("a", "b", "c")], bad_enabled=set())
    black, blue = p["variants"]
    assert p["comparison_incomplete"] is False
    assert {"source": "c", "reason": "ناموجود"} in black["incomplete_sources"]
    # b carries the product (black) but has no price for blue -> never hidden
    assert {"source": "b", "reason": "قیمت دریافت نشد"} in blue["incomplete_sources"]
    assert blue["comparison_incomplete"] is True


def test_mark_incomplete_reports_failed_sources():
    p = _product([_variant("black", [_offer("a", 100)])])
    mark_incomplete([p], [SimpleNamespace(name=n) for n in ("a", "z")], bad_enabled={"z"})
    assert p["comparison_incomplete"] is True
    assert any("z" in r for r in p["incomplete_reasons"])
    assert p["variants"][0]["comparison_incomplete"] is True


def test_runner_fastest_and_incomplete_end_to_end(tmp_path):
    cfg, base = make_project(tmp_path)
    srcs_rows = load_sources_yaml(tmp_path)
    srcs_rows[2]["path"] = "fixtures/none.csv"                    # shop_c fails
    cfg2, base2 = make_project(tmp_path / "q", sources=srcs_rows)
    res = run(cfg2, base_dir=base2)
    assert res.exit_code == 0
    p = next(p for p in res.doc["products"] if p["id"] == "iphone17-256")
    assert p["comparison_incomplete"] is True
    assert any("shop_c" in r for r in p["incomplete_reasons"])
    blue = next(v for v in p["variants"] if v["variant"] == "blue")
    assert blue["fastest"] and blue["fastest"]["source"] in ("shop_a", "shop_b")
    # shop_c failed this cycle -> flagged at product level, never silently ignored
    assert p["comparison_incomplete"] and any("shop_c" in r for r in p["incomplete_reasons"])
    assert blue["winner"]["shipping_label"]                       # shipping always stated separately
