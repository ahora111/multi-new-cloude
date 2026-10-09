import yaml
from conftest_helpers import make_project
from pricecompare.config import ConfigError, load_settings, load_sources, load_watchlist
from pricecompare.extract import Extractor


def _raises(fn, text):
    try:
        fn()
    except ConfigError as exc:
        assert text in str(exc), str(exc)
        return
    raise AssertionError("ConfigError not raised")


def test_unknown_setting_key_is_rejected(tmp_path):
    cfg, _ = make_project(tmp_path, settings={"outlier_ratoi": 3})
    _raises(lambda: load_settings(cfg), "unknown keys")


def test_invalid_thresholds_rejected(tmp_path):
    cfg, _ = make_project(tmp_path, settings={"match_review_threshold": 99, "match_auto_threshold": 90})
    _raises(lambda: load_settings(cfg), "match_review_threshold")


def test_source_requires_explicit_currency_unit(tmp_path):
    cfg, _ = make_project(tmp_path, sources=[{"name": "x", "type": "csv"}])
    _raises(lambda: load_sources(cfg), "currency_unit")
    cfg, _ = make_project(tmp_path / "b", sources=[{"name": "x", "type": "csv", "currency_unit": "dollar"}])
    _raises(lambda: load_sources(cfg), "toman' or 'rial")


def test_watchlist_validation(tmp_path):
    ex = Extractor()
    cfg, _ = make_project(tmp_path, watchlist=[{"id": "a", "brand": "apple"}])
    _raises(lambda: load_watchlist(cfg, ex), "'model' is required")
    cfg, _ = make_project(tmp_path / "b", watchlist=[{"id": "a", "brand": "apple", "model": "x"}, {"id": "a", "brand": "apple", "model": "y"}])
    _raises(lambda: load_watchlist(cfg, ex), "duplicate id")
    cfg, _ = make_project(tmp_path / "c", watchlist=[{"id": "a", "brand": "apple", "model": "x", "storag": 1}])
    _raises(lambda: load_watchlist(cfg, ex), "unknown keys")


def test_watchlist_normalises_values(tmp_path):
    cfg, _ = make_project(tmp_path, watchlist=[{"id": "a", "brand": "Apple", "model": "iPhone 17", "storage": "256GB",
                                               "region": "CH/A", "condition": "non_active", "colors": ["مشکی"]}])
    w = load_watchlist(cfg, Extractor())[0]
    assert (w.brand, w.storage_gb, w.region, w.condition, w.colors) == ("apple", 256, "cha", "nonactive", ["black"])
