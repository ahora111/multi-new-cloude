"""Eways / Hamrahtel plugins tested with fakes (no network, no credentials)."""
import importlib
import os
from types import SimpleNamespace
from conftest_helpers import make_project
from pricecompare.config import SourceConfig
from pricecompare.models import WatchItem
from pricecompare.runner import run
from pricecompare.sources import build_source


def _mod(name):
    try:
        return importlib.import_module(name)
    except ImportError:          # optional extras (tqdm/tenacity/playwright) not installed -> skip
        return None


LEG = "pricecompare.sources.vendor.eways_legacy"
HT = "pricecompare.sources.vendor.hamrahtel_scraper"
WATCH = [WatchItem(id="i", brand="apple", model="iPhone 17", storage_gb=256),
         WatchItem(id="a", brand="samsung", model="Galaxy A17 4G", storage_gb=128)]


def _fake_eways(monkeypatch, legacy, enriched):
    rows = [
        {"id": "1", "name": "گوشی اپل iPhone 17 256GB آبی", "category_id": 5, "detail_hint_cat_id": 5, "price": "641000000", "stock": 1, "specs": {}},
        {"id": "2", "name": "Samsung Galaxy A17 4G 128GB RAM 4GB", "category_id": 5, "detail_hint_cat_id": 5, "price": "97500000", "stock": 1, "specs": {}},
        {"id": "3", "name": "Sony Bravia TV 55", "category_id": 9, "detail_hint_cat_id": 9, "price": "999000000", "stock": 1, "specs": {}},
    ]
    monkeypatch.setattr(legacy, "login_eways", lambda u, p: object())
    monkeypatch.setattr(legacy, "get_and_parse_categories", lambda s: [{"id": 5}])
    monkeypatch.setattr(legacy, "init_category_index_global", lambda c: None)
    monkeypatch.setattr(legacy, "parse_selected_ids_string", lambda v: [])
    monkeypatch.setattr(legacy, "get_selected_categories_according_to_selection", lambda p, c: ([{"id": 5}], None))
    monkeypatch.setattr(legacy, "get_products_from_category_page", lambda *a: rows)
    monkeypatch.setattr(legacy, "condense_products_to_leaf", lambda r, c: {str(x["id"]): x for x in r.values()})

    def enrich(session, prods, pids):
        enriched.extend(sorted(pids))
        for pid in pids:
            prods[pid]["specs"] = {"رنگ": "آبی", "حافظه داخلی": "256 گیگابایت"} if pid == "1" else {}
    monkeypatch.setattr(legacy, "enrich_products_with_details", enrich)


def _eways_cfg(**opts):
    return SourceConfig("eways", "eways", "rial", options=opts)


def test_eways_maps_records_and_fetches_details_only_for_candidates(monkeypatch):
    legacy = _mod(LEG)
    if not legacy:
        return
    enriched = []
    _fake_eways(monkeypatch, legacy, enriched)
    monkeypatch.setenv("EWAYS_USERNAME", "u"); monkeypatch.setenv("EWAYS_PASSWORD", "p")
    offers = {o.source_offer_id: o for o in build_source(_eways_cfg()).fetch(WATCH)}
    assert set(offers) == {"1", "2"} and enriched == ["1", "2"]          # the TV never reaches the detail pages
    o = offers["1"]
    assert (o.currency_unit_raw, o.price_raw, o.stock, o.raw_color) == ("rial", 641_000_000, "IN_STOCK", "آبی")
    assert o.url.endswith("/Store/Detail/5/1")


def test_eways_details_none_skips_enrichment(monkeypatch):
    legacy = _mod(LEG)
    if not legacy:
        return
    enriched = []
    _fake_eways(monkeypatch, legacy, enriched)
    monkeypatch.setenv("EWAYS_USERNAME", "u"); monkeypatch.setenv("EWAYS_PASSWORD", "p")
    build_source(_eways_cfg(details="none")).fetch(WATCH)
    assert enriched == []


def test_eways_missing_credentials_and_login_failure_have_clear_errors(monkeypatch):
    legacy = _mod(LEG)
    if not legacy:
        return
    monkeypatch.delenv("EWAYS_USERNAME", raising=False); monkeypatch.delenv("EWAYS_PASSWORD", raising=False)
    for cfg, text in ((_eways_cfg(), "credentials missing"),):
        try:
            build_source(cfg).fetch(WATCH)
        except RuntimeError as exc:
            assert text in str(exc) and "EWAYS_USERNAME" in str(exc)
        else:
            raise AssertionError("no error")
    monkeypatch.setenv("EWAYS_USERNAME", "u"); monkeypatch.setenv("EWAYS_PASSWORD", "p")
    monkeypatch.setattr(legacy, "login_eways", lambda u, p: None)
    try:
        build_source(_eways_cfg()).fetch(WATCH)
    except RuntimeError as exc:
        assert "login failed" in str(exc)
    else:
        raise AssertionError("no error")


def test_eways_rial_is_converted_once_end_to_end(tmp_path, monkeypatch):
    legacy = _mod(LEG)
    if not legacy:
        return
    _fake_eways(monkeypatch, legacy, [])
    monkeypatch.setenv("EWAYS_USERNAME", "u"); monkeypatch.setenv("EWAYS_PASSWORD", "p")
    cfg, base = make_project(tmp_path, sources=[{"name": "eways", "type": "eways", "currency_unit": "rial"}],
                             watchlist=[{"id": "i", "brand": "apple", "model": "iPhone 17", "storage": 256}])
    res = run(cfg, base_dir=base)
    v = res.doc["products"][0]["variants"][0]
    assert v["winner"]["price_toman"] == 64_100_000


def _ht_products(scraper):
    P = scraper.Product
    return [P("iPhone", "iPhone 17 256GB", "64,500,000", "آبی"), P("iPhone", "iPhone 17 256GB", "64,900,000", "آبی"),
            P("Galaxy", "Galaxy A17 4G 128GB", "9,800,000", "مشکی")]


def test_hamrahtel_ids_are_price_independent_urls_and_category_filter(monkeypatch):
    sc = _mod(HT)
    if not sc:
        return
    seen = {}

    def fake(opts):
        seen["cats"] = list(sc.CATEGORIES)
        seen["timeout"] = opts.page_timeout_ms
        return _ht_products(sc), True
    monkeypatch.setattr(sc, "fetch_all_products", fake)
    cfg = SourceConfig("hamrahtel", "hamrahtel", "toman", options={"strategy": "legacy", "categories": ["mobile"], "page_timeout_ms": 1234})
    recs = build_source(cfg).fetch([])
    assert seen["cats"] == ["mobile"] and seen["timeout"] == 1234
    assert [r.source_offer_id for r in recs] == ["iPhone|iPhone 17 256GB|آبی", "iPhone|iPhone 17 256GB|آبی#2", "Galaxy|Galaxy A17 4G 128GB|مشکی"]
    assert recs[0].url.endswith("category=mobile") and recs[0].currency_unit_raw == "toman" and recs[0].price_raw == 64_500_000
    assert len(sc.CATEGORIES) == 4                                # global state restored


def test_hamrahtel_zero_products_is_a_failure_not_an_empty_success(monkeypatch):
    sc = _mod(HT)
    if not sc:
        return
    monkeypatch.setattr(sc, "fetch_all_products", lambda o: ([], False))
    try:
        build_source(SourceConfig("hamrahtel", "hamrahtel", "toman", options={"strategy": "legacy"})).fetch([])
    except RuntimeError as exc:
        assert "zero products" in str(exc)
    else:
        raise AssertionError("no error")
    try:
        build_source(SourceConfig("hamrahtel", "hamrahtel", "toman", options={"categories": ["cars"]})).fetch([])
    except ValueError as exc:
        assert "unknown categories" in str(exc)
    else:
        raise AssertionError("no error")


def test_both_real_sources_together_pick_the_cheapest(tmp_path, monkeypatch):
    legacy, sc = _mod(LEG), _mod(HT)
    if not (legacy and sc):
        return
    _fake_eways(monkeypatch, legacy, [])
    monkeypatch.setattr(sc, "fetch_all_products", lambda o: (_ht_products(sc), True))
    monkeypatch.setenv("EWAYS_USERNAME", "u"); monkeypatch.setenv("EWAYS_PASSWORD", "p")
    srcs = [{"name": "eways", "type": "eways", "currency_unit": "rial", "priority": 10},
            {"name": "hamrahtel", "type": "hamrahtel", "currency_unit": "toman", "priority": 20, "strategy": "legacy"}]
    wl = [{"id": "i", "brand": "apple", "model": "iPhone 17", "storage": 256}, {"id": "a", "brand": "samsung", "model": "Galaxy A17 4G", "storage": 128, "ram": 4}]
    cfg, base = make_project(tmp_path, sources=srcs, watchlist=wl)
    res = run(cfg, base_dir=base)
    assert res.exit_code == 0
    by = {p["id"]: p["variants"] for p in res.doc["products"]}
    blue = next(v for v in by["i"] if v["variant"] == "blue")
    assert blue["winner"]["source"] == "eways" and blue["winner"]["price_toman"] == 64_100_000   # 641M rial < 64.5M toman
    assert by["a"][0]["winner"]["price_toman"] == 9_750_000                                       # 97.5M rial < 9.8M toman
