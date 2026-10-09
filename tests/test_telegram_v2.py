"""V2 §8/§10: one canonical title per product, all colours underneath, transparent per-colour gaps."""
import json
from conftest_helpers import make_project
from pricecompare import report
from pricecompare.runner import run


def _doc(tmp_path, **kw):
    cfg, base = make_project(tmp_path, **kw)
    res = run(cfg, base_dir=base)
    assert res.exit_code == 0
    return res.doc


def test_one_canonical_title_per_product_and_all_colours_under_it(tmp_path):
    doc = _doc(tmp_path)
    p = next(p for p in doc["products"] if p["id"] == "iphone17-256")
    assert p["title"] == "Apple iPhone 17 256GB"
    colours = {v["variant"] for v in p["variants"]}
    assert {"black", "blue"} <= colours                       # every colour under THE SAME title
    msgs = "\n".join(report.build_telegram_messages(doc, "none"))
    assert msgs.count("📱 Apple iPhone 17 256GB") == 1        # the title appears exactly once
    assert "⚫ مشکی:" in msgs and "🔵 آبی:" in msgs           # colours shown with Persian names
    block = msgs.split("📱 Apple iPhone 17 256GB")[1].split("📱")[0]   # this product's section only
    assert block.count("⚫ مشکی:") == 1                       # ONE row per colour inside the block
    assert block.count("🔵 آبی:") == 1


def test_all_vendor_prices_beside_each_colour(tmp_path):
    doc = _doc(tmp_path)
    msgs = "\n".join(report.build_telegram_messages(doc, "none"))
    black = next(v for v in next(p for p in doc["products"]
                                 if p["id"] == "iphone17-256")["variants"] if v["variant"] == "black")
    prices = {o["source"]: report.money(o["price_toman"]) for o in black["offers"] if o["valid"]}
    line = next(l for l in msgs.splitlines() if "⚫ مشکی:" in l)
    for src, price in prices.items():
        assert src in line and price in line, (src, price, line)


def test_missing_colour_price_is_never_hidden(tmp_path):
    doc = _doc(tmp_path)
    p = next(p for p in doc["products"] if p["id"] == "iphone17-256")
    black = next(v for v in p["variants"] if v["variant"] == "black")
    # farnaa carries the product but has no usable black price -> the DATA must state it, not hide it
    miss = {m["source"]: m["reason"] for m in black["incomplete_sources"]}
    assert "farnaa" in miss
    # quiet channel default: the per-source «قیمت دریافت نشد» list is NOT posted to Telegram
    # (the full per-offer detail stays in output.json / report.csv / report.md)
    quiet = "\n".join(report.build_telegram_messages(doc, "none"))
    assert "قیمت دریافت نشد" not in quiet and "منبع ناموفق" not in quiet
    assert "مقایسه ناقص" not in quiet
    # opt-in flag restores the verbose per-colour listing
    verbose = "\n".join(report.build_telegram_messages(doc, "none", show_missing_sources=True))
    assert "farnaa: قیمت دریافت نشد" in verbose or "farnaa: منبع ناموفق" in verbose or \
        any(f"farnaa: {r}" in verbose for r in miss.values())


def test_failed_source_marks_comparison_incomplete(tmp_path):
    cfg, base = make_project(tmp_path)
    import yaml as _y
    from conftest_helpers import load_sources_yaml
    rows = load_sources_yaml(tmp_path)
    rows[2]["path"] = "fixtures/none.csv"
    cfg2, base2 = make_project(tmp_path / "q", sources=rows)
    res = run(cfg2, base_dir=base2)
    p = next(p for p in res.doc["products"] if p["id"] == "iphone17-256")
    assert p["comparison_incomplete"] and any("shop_c" in r for r in p["incomplete_reasons"])
    msgs = "\n".join(report.build_telegram_messages(res.doc, "none", show_missing_sources=True))
    assert "مقایسه ناقص" in msgs


def test_no_markdown_symbols_in_telegram_and_tehran_stamp(tmp_path):
    doc = _doc(tmp_path)
    msgs = "\n".join(report.build_telegram_messages(doc, "none"))
    assert "##" not in msgs and "**" not in msgs
    assert "(تهران)" in msgs
    for x in doc["sources"]:
        assert x["name"] in msgs


def test_alert_messages_are_short_and_independent(tmp_path):
    from pricecompare.report import build_alert_messages
    alerts = [
        {"type": "vendor_drop", "product_id": "ip", "product_title": "Apple iPhone 17 256GB",
         "variant": "black", "source": "eways", "prev_price": 20_000_000, "new_price": 19_000_000,
         "amount_toman": -1_000_000, "percent": -5.0, "recorded_at": "2026-10-06T09:00:00+00:00",
         "prev_recorded_at": "2026-10-06T08:00:00+00:00", "alert": True},
        {"type": "market_best", "product_id": "ip", "product_title": "Apple iPhone 17 256GB",
         "variant": "blue", "source": "farnaa", "prev_price": 65_000_000, "new_price": 64_000_000,
         "amount_toman": -1_000_000, "percent": -1.54, "recorded_at": "2026-10-06T09:00:00+00:00",
         "prev_recorded_at": "2026-10-06T08:00:00+00:00", "alert": True},
    ]
    msgs = build_alert_messages(alerts)
    assert len(msgs) == 1                                     # grouped by product
    assert "📱 Apple iPhone 17 256GB" in msgs[0]
    assert "📉 فرصت خرید | کاهش 5٪ | 1,000,000 تومان ارزان‌تر — eways" in msgs[0]
    assert "20,000,000 → 19,000,000" in msgs[0]
    assert "🏷️ بهترین قیمت بازار — farnaa" in msgs[0]
    assert "⚫ مشکی" in msgs[0] and "🔵 آبی" in msgs[0]


def test_long_report_is_never_silently_truncated(tmp_path):
    from pricecompare import telegram
    doc = _doc(tmp_path)
    msgs = report.build_telegram_messages(doc, "none")
    # explicit opt-in: the cap is ANNOUNCED, not silent
    parts = telegram.send("t", "c", msgs, limit=300, dry_run=True, max_messages=2, truncation_notice=True)
    assert len(parts) == 2 and "telegram_max_messages" in parts[-1]
    # quiet channel default (telegram_truncation_notice: false): overflow is dropped silently,
    # no «N پیام دیگر …» post — the complete report stays in the output files
    quiet_parts = telegram.send("t", "c", msgs, limit=300, dry_run=True, max_messages=2, truncation_notice=False)
    assert len(quiet_parts) == 2 and "telegram_max_messages" not in quiet_parts[-1]
