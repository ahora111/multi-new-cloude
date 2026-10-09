"""V2 §11: adding a new source without touching the core — config row + delivery entry is enough."""
import json
import shutil
from datetime import datetime, timezone
from conftest_helpers import make_project, load_sources_yaml
import yaml
from pricecompare.runner import run
from pricecompare.sources import REGISTRY


def _add_shop_d(tmp_path, delivery=True, enabled=True):
    cfg, base = make_project(tmp_path / "p")
    (tmp_path / "p" / "fixtures" / "shop_d.csv").write_text(
        "sku,title,price,stock,link\nd1,iPhone 17 256GB Blue,60000000,موجود,https://d.example/1\n",
        encoding="utf-8")
    rows = load_sources_yaml(tmp_path / "p")
    rows.append({"name": "shop_d", "type": "csv", "currency_unit": "toman", "priority": 5,
                 "min_expected_products": 1, "enabled": enabled, "path": "fixtures/shop_d.csv",
                 "columns": {"id": "sku", "title": "title", "price": "price", "stock": "stock", "url": "link"}})
    (tmp_path / "p" / "config" / "sources.yaml").write_text(
        yaml.safe_dump({"sources": rows}, allow_unicode=True), encoding="utf-8")
    if delivery:
        dy = tmp_path / "p" / "config" / "delivery.yaml"
        data = yaml.safe_load(dy.read_text(encoding="utf-8"))
        data["sources"]["shop_d"] = {
            "order_windows": [{"start": "09:00", "end": "12:00", "ship_at": "13:00",
                               "delivery_at": "14:00", "delivery_day_offset": 0}],
            "verified": True}
        dy.write_text(yaml.safe_dump(data, allow_unicode=True), encoding="utf-8")
    return cfg, base


FIXED_NOW = datetime(2026, 10, 6, 8, 30, tzinfo=timezone.utc)      # 12:00 Tehran (Tuesday)


def test_new_source_joins_the_shared_cycle_and_delivery(tmp_path):
    cfg, base = _add_shop_d(tmp_path)
    res = run(cfg, base_dir=base, now=FIXED_NOW)                # 12:00 Tehran -> deterministic delivery
    assert res.exit_code == 0
    st = {s["name"]: s for s in res.doc["sources"]}
    assert "shop_d" in st and st["shop_d"]["status"] == "ok"
    # it automatically takes part in comparison + becomes the cheapest blue AND the fastest
    p = next(p for p in res.doc["products"] if p["id"] == "iphone17-256")
    blue = next(v for v in p["variants"] if v["variant"] == "blue")
    assert blue["winner"]["source"] == "shop_d" and blue["winner"]["price_toman"] == 60_000_000
    assert blue["fastest"]["source"] == "shop_d" and blue["fastest"]["delivery_label"]
    assert "امروز 14:00" in blue["fastest"]["delivery_label"] and "سفارش تا 12:00" in blue["fastest"]["delivery_label"]
    assert blue["delivery"]["shop_d"]["verified"] is True
    # other sources are unaffected: black still belongs to shop_a
    black = next(v for v in p["variants"] if v["variant"] == "black")
    assert black["winner"]["source"] == "shop_a"


def test_disabling_a_source_keeps_history_and_other_sources(tmp_path):
    cfg, base = _add_shop_d(tmp_path)
    run(cfg, base_dir=base)
    hist = tmp_path / "p" / "history.jsonl"
    lines_before = len(hist.read_text(encoding="utf-8").splitlines())
    assert lines_before >= 1
    rows = load_sources_yaml(tmp_path / "p")
    for r in rows:
        if r["name"] == "shop_d":
            r["enabled"] = False
    (tmp_path / "p" / "config" / "sources.yaml").write_text(
        yaml.safe_dump({"sources": rows}, allow_unicode=True), encoding="utf-8")
    res = run(cfg, base_dir=base)
    assert res.exit_code == 0
    st = {s["name"] for s in res.doc["sources"]}
    assert "shop_d" not in st                                  # disabled = out of the cycle
    # history was never wiped (append-only)
    lines_after = len(hist.read_text(encoding="utf-8").splitlines())
    assert lines_after == lines_before + 1
    # competitors return to their previous state
    p = next(p for p in res.doc["products"] if p["id"] == "iphone17-256")
    blue = next(v for v in p["variants"] if v["variant"] == "blue")
    assert blue["winner"]["source"] == "shop_b"


def test_new_source_failure_is_isolated(tmp_path):
    cfg, base = make_project(tmp_path / "p")
    rows = load_sources_yaml(tmp_path / "p")
    rows.append({"name": "shop_d", "type": "csv", "currency_unit": "toman", "priority": 5,
                 "path": "fixtures/missing_d.csv",
                 "columns": {"id": "sku", "title": "title", "price": "price", "stock": "stock"}})
    (tmp_path / "p" / "config" / "sources.yaml").write_text(
        yaml.safe_dump({"sources": rows}, allow_unicode=True), encoding="utf-8")
    res = run(cfg, base_dir=base)
    assert res.exit_code == 0                                  # the cycle still completes
    st = {s["name"]: s for s in res.doc["sources"]}
    assert st["shop_d"]["status"] == "failed" and st["shop_a"]["status"] == "ok"


def test_custom_adapter_class_registers_without_core_changes(tmp_path):
    from pricecompare.sources.base import Source
    import pricecompare.sources as srcs_pkg

    class MyShop(Source):
        type_name = "my_shop_test"

        def records(self, watchlist):
            return [{"id": "m1", "title": "iPhone 17 256GB Green", "price": 59_000_000,
                     "stock": "موجود", "url": "https://m.example/1", "color": "سبز"}]

    srcs_pkg.REGISTRY[MyShop.type_name] = MyShop
    try:
        rows = [{"name": "myshop", "type": "my_shop_test", "currency_unit": "toman"}]
        cfg, base = make_project(tmp_path, sources=rows,
                                 watchlist=[{"id": "ip17", "brand": "apple", "model": "iPhone 17",
                                             "storage": 256}])
        res = run(cfg, base_dir=base)
        assert res.exit_code == 0
        p = next(p for p in res.doc["products"] if p["id"] == "ip17")
        green = next(v for v in p["variants"] if v["variant"] == "green")
        assert green["winner"]["source"] == "myshop" and green["winner"]["price_toman"] == 59_000_000
    finally:
        srcs_pkg.REGISTRY.pop(MyShop.type_name, None)
