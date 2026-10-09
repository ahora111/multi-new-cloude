"""V2 §5: per-source order windows & delivery estimates to Qazvin (Asia/Tehran)."""
from datetime import date, datetime, timezone, timedelta
import pytest
import yaml
from conftest_helpers import make_project, ROOT
from pricecompare.delivery import (DeliveryConfigError, OrderWindow, SourceSchedule, estimate,
                                   format_estimate, load_schedules, parse_date, parse_hhmm,
                                   UNKNOWN_LABEL, SHIPPING_UNKNOWN_LABEL)
from pricecompare.runner import run

T = timezone.utc
# Tehran == UTC+3:30 (no DST). Tuesday 2026-10-06 08:30 UTC == 12:00 Tehran
TUE_NOON = datetime(2026, 10, 6, 8, 30, tzinfo=T)
TUE_1430 = datetime(2026, 10, 6, 11, 0, tzinfo=T)      # 14:30 Tehran
TUE_1231 = datetime(2026, 10, 6, 9, 1, tzinfo=T)       # 12:31 Tehran (just after a 12:00 cut-off)
FRI_MORNING = datetime(2026, 10, 9, 5, 30, tzinfo=T)   # 09:00 Tehran on a FRIDAY
WED_NOON = datetime(2026, 10, 7, 8, 30, tzinfo=T)      # 12:00 Tehran Wednesday


def _sch(**kw):
    windows = kw.pop("windows", [OrderWindow(parse_hhmm("09:00", "s"), parse_hhmm("12:00", "e"),
                                             parse_hhmm("13:30", "sh"), parse_hhmm("18:00", "d"), 0)])
    return SourceSchedule(name=kw.pop("name", "x"), windows=windows, **kw)


def test_order_before_and_exactly_at_cut_off_is_same_day():
    e = estimate(_sch(), TUE_NOON, "s")
    assert e.status == "ok" and e.same_day
    assert e.delivery_at.hour == 18 and e.order_deadline.hour == 12
    assert "امروز" in e.label and "سفارش تا 12:00" in e.label


def test_order_exactly_at_cut_off_still_accepted():
    e = estimate(_sch(), TUE_NOON, "s")          # 12:00 == cut-off -> accepted
    assert e.same_day and "امروز" in e.label


def test_order_after_cut_off_falls_to_next_working_day():
    e = estimate(_sch(), TUE_1231, "s")          # 12:31 Tehran -> next window = tomorrow
    assert e.status == "ok" and not e.same_day
    assert e.delivery_at.hour == 18
    assert "امروز" not in e.label and "سفارش تا 12:00" in e.label


def test_friday_and_custom_holidays_are_skipped():
    sch = _sch(active_weekdays={5, 6, 0, 1, 2})                  # Sat..Thu (Iran work week)
    e = estimate(sch, FRI_MORNING, "s")                          # Friday morning
    assert e.delivery_at.weekday() == 5                          # Saturday
    sch2 = _sch(holidays={parse_date("2026-10-06", "h")})        # Tuesday is a holiday
    e2 = estimate(sch2, TUE_NOON, "s")
    assert e2.delivery_at.date() == date(2026, 10, 7)            # Wednesday (Tehran)


def test_next_day_delivery_offset_one():
    sch = _sch(windows=[OrderWindow(parse_hhmm("00:00", "w"), parse_hhmm("23:00", "e"),
                                    parse_hhmm("23:30", "s"), parse_hhmm("10:00", "d"), 1)])
    e = estimate(sch, TUE_NOON, "hamrahtel")
    assert e.delivery_at.hour == 10 and "فردا" in e.label and "سفارش تا 23:00" in e.label


def test_multiple_windows_use_the_next_open_one():
    sch = _sch(windows=[OrderWindow(parse_hhmm("09:00", "a"), parse_hhmm("12:00", "b"),
                                    parse_hhmm("13:00", "c"), parse_hhmm("16:00", "d"), 0),
                        OrderWindow(parse_hhmm("15:00", "a2"), parse_hhmm("18:00", "b2"),
                                    parse_hhmm("18:30", "c2"), parse_hhmm("21:00", "d2"), 0)])
    e = estimate(sch, TUE_1430, "s")             # 14:30: first window closed, second open
    assert e.order_deadline.hour == 18 and e.delivery_at.hour == 21 and e.same_day


def test_estimated_times_are_labelled_and_verified_times_are_not():
    assert "(تقریبی)" in estimate(_sch(verified=False), TUE_NOON, "s").label
    assert "(تقریبی)" not in estimate(_sch(verified=True), TUE_NOON, "s").label


def test_no_config_or_empty_config_means_unknown_delivery():
    assert estimate(None, TUE_NOON, "s").label == UNKNOWN_LABEL
    assert estimate(_sch(windows=[]), TUE_NOON, "s").label == UNKNOWN_LABEL


def test_sources_are_independent():
    early = _sch(name="early")
    late = _sch(name="late", windows=[OrderWindow(parse_hhmm("09:00", "a"), parse_hhmm("23:00", "b"),
                                                  parse_hhmm("23:30", "c"), parse_hhmm("10:00", "d"), 1)])
    e1, e2 = estimate(early, TUE_NOON, "early"), estimate(late, TUE_NOON, "late")
    assert e1.delivery_at < e2.delivery_at and e1.same_day and not e2.same_day


def test_shipping_is_quoted_separately():
    e = estimate(_sch(shipping_cost_toman=80_000), TUE_NOON, "s")
    assert "80,000" in e.shipping_label and "جدا" in e.shipping_label
    assert estimate(_sch(), TUE_NOON, "s").shipping_label == SHIPPING_UNKNOWN_LABEL


def test_delivery_yaml_loading_and_validation():
    schs = load_schedules(ROOT / "config" / "delivery.yaml")
    assert {"eways", "hamrahtel", "shop_a"} <= set(schs)
    assert load_schedules(ROOT / "config" / "no_such_file.yaml") == {}
    with pytest.raises(DeliveryConfigError):
        load_schedules(ROOT / "fixtures" / "shop_a.json")            # wrong structure
    tmp = ROOT / "fixtures" / "_never_used.yaml"
    tmp.write_text(yaml.safe_dump({"sources": {"x": {"order_windows": [
        {"start": "09:00", "end": "12:00", "ship_at": "13:00", "delivery_at": "11:00"}]}}}), encoding="utf-8")
    try:
        with pytest.raises(DeliveryConfigError):
            load_schedules(tmp)                                      # same-day arrival before dispatch
    finally:
        tmp.unlink()
    with pytest.raises(DeliveryConfigError):
        parse_hhmm("25:00", "w")


def test_runner_attaches_delivery_and_cycle_metadata(tmp_path):
    cfg, base = make_project(tmp_path)
    res = run(cfg, base_dir=base)
    assert res.exit_code == 0
    doc = res.doc
    assert doc["cycle"]["timezone"] == "Asia/Tehran" and doc["cycle"]["interval_minutes"] == 60
    assert doc["cycle"]["started_at"] and doc["cycle"]["finished_at"]
    p = next(p for p in doc["products"] if p["id"] == "iphone17-256")
    blue = next(v for v in p["variants"] if v["variant"] == "blue")
    assert blue["fastest"]["source"] and blue["fastest"]["delivery_label"]
    assert "سفارش تا" in blue["fastest"]["delivery_label"]
    assert set(blue["delivery"]) == {"shop_a", "shop_b", "shop_c"}
    for e in blue["delivery"].values():
        assert "delivery_at" in e and "label" in e and "shipping_label" in e
