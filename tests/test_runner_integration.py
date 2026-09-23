import json
import os
from datetime import datetime, timezone
from pathlib import Path
import yaml
from conftest_helpers import make_project, load_sources_yaml
from pricecompare.cli import main
from pricecompare.runner import run

NOW = datetime.now(timezone.utc)


def _go(tmp_path, **kw):
    cfg, base = make_project(tmp_path, **kw.pop("proj", {}))
    return cfg, base, run(cfg, base_dir=base, **kw)


def _doc(tmp_path):
    return json.loads((tmp_path / "out" / "output.json").read_text(encoding="utf-8"))


def _winners(doc):
    return {(p["id"], v["variant"]): (v["winner"]["source"], v["winner"]["price_toman"])
            for p in doc["products"] for v in p["variants"] if v["winner"]}


EXPECTED = {
    ("iphone17-256", "black"): ("shop_a", 64_900_000),        # shop_a CH/A cheapest black
    ("iphone17-256", "blue"): ("shop_b", 64_100_000),         # shop_b is RIAL: 641,000,000 -> 64,100,000
    ("iphone17pro-256", "silver"): ("shop_b", 89_100_000),
    ("galaxy-a17-4g-128", "black"): ("shop_b", 9_750_000),
    ("redmi-note-14-256-8", "black"): ("shop_b", 13_650_000),  # shop_a cheaper 13.7M? no: out of stock
    ("redmi-note-14-256-8", "gray"): ("shop_b", 13_700_000),   # shop_c typo 138,000 is an outlier
}


def test_end_to_end_winners_and_units(tmp_path):
    _, _, res = _go(tmp_path)
    assert res.exit_code == 0
    assert _winners(_doc(tmp_path)) == EXPECTED


def test_traps_never_leak_into_prices(tmp_path):
    _go(tmp_path)
    titles = " ".join(o["title"] for p in _doc(tmp_path)["products"] for v in p["variants"] for o in v["offers"])
    for bad in ("Pro Max", "17e", "iPhone 17 Air", "A17 5G", "Note 14 Pro"):
        assert bad not in titles.replace("iPhone 17 Pro 256GB", ""), bad


def test_not_found_and_summary(tmp_path):
    _go(tmp_path)
    d = _doc(tmp_path)
    assert d["not_found"] == ["pixel-10-pro-256"] and d["schema_version"] == "1.0"
    assert d["summary"]["products_found"] == 4 and d["summary"]["suspect_offers"] == 2


def test_all_output_files_written_and_csv_is_clean(tmp_path):
    _go(tmp_path)
    out = tmp_path / "out"
    for f in ("output.json", "report.csv", "report.md", "run_summary.json", "matching_report.json"):
        assert (out / f).exists(), f
    rows = (out / "report.csv").read_text(encoding="utf-8").splitlines()
    assert rows[0].lstrip("\ufeff").startswith("product_id,model,variant,winner_source") and len(rows) == 11
    assert "🏆" in (out / "report.md").read_text(encoding="utf-8")


def test_result_is_independent_of_source_order(tmp_path):
    cfg, base = make_project(tmp_path / "a")
    r1 = run(cfg, base_dir=base)
    srcs = load_sources_yaml(tmp_path / "a")
    cfg2, base2 = make_project(tmp_path / "b", sources=list(reversed(srcs)))
    r2 = run(cfg2, base_dir=base2)
    assert _winners(r1.doc) == _winners(r2.doc)


def test_adding_a_fourth_source_needs_only_a_config_row(tmp_path):
    cfg, base = make_project(tmp_path)
    srcs = load_sources_yaml(tmp_path)
    (tmp_path / "fixtures" / "shop_d.csv").write_text(
        "sku,title,price,stock,link\nd1,iPhone 17 256GB Blue,60000000,موجود,https://d.example/1\n", encoding="utf-8")
    srcs.append({"name": "shop_d", "type": "csv", "currency_unit": "toman", "priority": 5,
                 "path": "fixtures/shop_d.csv", "columns": {"id": "sku", "title": "title", "price": "price", "stock": "stock", "url": "link"}})
    cfg, base = make_project(tmp_path / "x", sources=srcs)
    (tmp_path / "x" / "fixtures" / "shop_d.csv").write_text((tmp_path / "fixtures" / "shop_d.csv").read_text(encoding="utf-8"), encoding="utf-8")
    res = run(cfg, base_dir=base)
    assert _winners(res.doc)[("iphone17-256", "blue")] == ("shop_d", 60_000_000)


def test_one_broken_source_is_isolated_and_reported(tmp_path):
    srcs = yaml.safe_load(open(Path(__file__).parent.parent / "config" / "sources.yaml", encoding="utf-8"))["sources"]
    srcs[1]["path"] = "fixtures/does_not_exist.html"
    cfg, base = make_project(tmp_path, sources=srcs)
    res = run(cfg, base_dir=base)
    assert res.exit_code == 0
    st = {s["name"]: s for s in res.doc["sources"]}
    assert st["shop_b"]["status"] == "failed" and st["shop_a"]["status"] == "ok"
    assert any("shop_b" in w for w in res.doc["warnings"])
    assert ("iphone17-256", "blue") in _winners(res.doc) and _winners(res.doc)[("iphone17-256", "blue")][0] == "shop_c"


def test_all_sources_failed_keeps_previous_output_and_exit_code(tmp_path):
    cfg, base = make_project(tmp_path)
    assert run(cfg, base_dir=base).exit_code == 0
    before = (tmp_path / "out" / "output.json").read_text(encoding="utf-8")
    srcs = load_sources_yaml(tmp_path)
    for s in srcs:
        s["path"] = "fixtures/none.txt"
    cfg2, _ = make_project(tmp_path / "again", sources=srcs, settings={"output_dir": str(tmp_path / "out")})
    res = run(cfg2, base_dir=base)
    assert res.exit_code == 2
    assert (tmp_path / "out" / "output.json").read_text(encoding="utf-8") == before


def test_require_all_sources_flag(tmp_path):
    make_project(tmp_path / "p")
    srcs = load_sources_yaml(tmp_path / "p")
    srcs[0]["path"] = "fixtures/none.json"
    cfg, base = make_project(tmp_path / "q", sources=srcs)
    res = run(cfg, base_dir=base, require_all=True)
    assert res.exit_code == 3 and not (tmp_path / "q" / "out" / "output.json").exists()


def test_degraded_source_is_reported_and_never_wins(tmp_path):
    make_project(tmp_path / "p")
    srcs = load_sources_yaml(tmp_path / "p")
    srcs[1]["min_expected_products"] = 50          # shop_b returns only 7 -> degraded
    cfg, base = make_project(tmp_path / "q", sources=srcs)
    res = run(cfg, base_dir=base)
    assert {s["name"]: s["status"] for s in res.doc["sources"]}["shop_b"] == "degraded"
    assert all(w[0] != "shop_b" for w in _winners(res.doc).values())


def test_wrong_declared_unit_is_detected(tmp_path):
    make_project(tmp_path / "p")
    srcs = load_sources_yaml(tmp_path / "p")
    srcs[1]["currency_unit"] = "toman"             # shop_b is really rial -> 10x too expensive
    cfg, base = make_project(tmp_path / "q", sources=srcs)
    res = run(cfg, base_dir=base)
    assert any("ریال/تومان" in w for w in res.doc["warnings"])
    assert res.summary["needs_review_variants"] > 0


def test_dry_run_writes_nothing(tmp_path):
    cfg, base = make_project(tmp_path)
    res = run(cfg, base_dir=base, dry_run=True)
    assert res.exit_code == 0 and not (tmp_path / "out").exists() and not (tmp_path / "history.jsonl").exists()


def test_history_alert_uses_setting(tmp_path):
    cfg, base = make_project(tmp_path)
    run(cfg, base_dir=base)
    hist = tmp_path / "history.jsonl"
    rec = json.loads(hist.read_text(encoding="utf-8").splitlines()[-1])
    for k in rec["prices"]:
        rec["prices"][k]["price"] *= 2               # pretend yesterday everything cost double
    hist.write_text(json.dumps(rec) + "\n", encoding="utf-8")
    res = run(cfg, base_dir=base)
    assert any("تغییر قیمت" in w for w in res.doc["warnings"])
    cfg2, _ = make_project(tmp_path / "q", settings={"history_alert_pct": 90, "history_file": str(hist)})
    assert not any("تغییر قیمت" in w for w in run(cfg2, base_dir=base).doc["warnings"])


def test_review_as_match_setting_and_review_queue(tmp_path):
    wl = [{"id": "x", "brand": "apple", "model": "iPhone 17", "storage": 256, "region": "CH/A"}]
    cfg, base = make_project(tmp_path / "a", watchlist=wl)
    r1 = run(cfg, base_dir=base)
    assert r1.summary["review_items"] > 0 and r1.summary["products_found"] == 1     # only the explicit CH/A offer priced
    cfg2, base2 = make_project(tmp_path / "b", watchlist=wl, settings={"review_as_match": True})
    r2 = run(cfg2, base_dir=base2)
    assert len(r2.doc["products"][0]["variants"]) >= len(r1.doc["products"][0]["variants"])


def test_overrides_force_match_and_force_split(tmp_path):
    cfg, base = make_project(tmp_path)
    (tmp_path / "config" / "overrides.yaml").write_text(yaml.safe_dump({
        "force_split": [{"source": "shop_c", "source_offer_id": "c1"}],
        "force_match": []}), encoding="utf-8")
    res = run(cfg, base_dir=base)
    blue = next(v for v in res.doc["products"][0]["variants"] if v["variant"] == "blue")
    assert all(o["source"] != "shop_c" for o in blue["offers"])


def test_concurrent_run_is_blocked_by_lock(tmp_path):
    cfg, base = make_project(tmp_path)
    (tmp_path / "run.lock").write_text(str(os.getpid()), encoding="utf-8")   # a live process holds the lock
    assert run(cfg, base_dir=base).exit_code == 5
    (tmp_path / "run.lock").write_text("999999", encoding="utf-8")          # dead pid -> stale lock is taken over
    assert run(cfg, base_dir=base).exit_code == 0


def test_config_error_exit_code(tmp_path):
    cfg, base = make_project(tmp_path, settings={"nope": 1})
    assert run(cfg, base_dir=base).exit_code == 4


def test_cli_run_and_explain_and_match_report(tmp_path, capsys=None):
    cfg, base = make_project(tmp_path)
    assert main(["--config-dir", cfg, "--base-dir", base, "run"]) == 0
    assert main(["--config-dir", cfg, "--base-dir", base, "match-report", "--status", "NO_MATCH"]) == 0
    assert main(["--config-dir", cfg, "--base-dir", base, "explain", "iphone17-256"]) == 0
    assert main(["--config-dir", cfg, "--base-dir", base, "explain", "nope"]) == 1
    assert main(["--config-dir", cfg, "--base-dir", base, "run", "--only-source", "zzz"]) == 4


def test_closest_catalog_titles_helper():
    from pricecompare.extract import Extractor
    from pricecompare.models import WatchItem
    from pricecompare.runner import closest_catalog_titles
    ex = Extractor()
    w = WatchItem(id="r", brand="xiaomi", model="Redmi Note 14")
    near = closest_catalog_titles(w, ex.parse(w.model), ["Xiaomi Redmi Note 15 256GB", "Samsung Galaxy A17", "Redmi Note 14 Pro 128GB", "TV 55"], ex)
    assert near[0] in ("Redmi Note 14 Pro 128GB",) and "Samsung Galaxy A17" not in near and "TV 55" not in near


def test_show_offers_prints_closest_titles_for_missing_products(tmp_path, capsys=None):
    import io, contextlib
    cfg, base = make_project(tmp_path)
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        main(["--config-dir", cfg, "--base-dir", base, "run", "--dry-run", "--show-offers", "2"])
    out = buf.getvalue()
    assert "sample offers per source" in out and "closest catalog titles" in out and "pixel-10-pro-256 @" in out


def test_color_merge_lets_differently_named_colours_compete(tmp_path):
    import yaml as _y
    wl = [{"id": "x", "brand": "apple", "model": "iPhone 17", "storage": 256}]
    cfg, base = make_project(tmp_path, watchlist=wl)
    v0 = {v["variant"]: v for v in run(cfg, base_dir=base).doc["products"][0]["variants"]}
    assert set(v0) == {"blue", "black", "بدون رنگ/مشخصه"}
    (tmp_path / "config" / "overrides.yaml").write_text(_y.safe_dump({"color_merge": [{"watch_id": "x", "colors": ["blue"], "as": "black"}]}), encoding="utf-8")
    v1 = {v["variant"]: v for v in run(cfg, base_dir=base).doc["products"][0]["variants"]}
    assert set(v1) == {"black", "بدون رنگ/مشخصه"}
    assert len(v1["black"]["offers"]) == len(v0["black"]["offers"]) + len(v0["blue"]["offers"])
    assert len(v1["بدون رنگ/مشخصه"]["offers"]) == len(v0["بدون رنگ/مشخصه"]["offers"])


def test_color_merge_validation(tmp_path):
    import yaml as _y
    cfg, base = make_project(tmp_path)
    (tmp_path / "config" / "overrides.yaml").write_text(_y.safe_dump({"color_merge": [{"watch_id": "x"}]}), encoding="utf-8")
    assert run(cfg, base_dir=base).exit_code == 4
