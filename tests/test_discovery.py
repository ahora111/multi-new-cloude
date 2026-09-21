"""Discovery: every phone in the catalogs is compared, cheapest valid price PER COLOUR, grouped into separate posts."""
import yaml
from conftest_helpers import make_project
from pricecompare import history, telegram
from pricecompare.config import Discovery, Settings
from pricecompare.discovery import discover
from pricecompare.extract import Extractor
from pricecompare.models import Offer
from pricecompare.report import build_telegram_messages
from pricecompare.runner import enrich, run

ex, st = Extractor(), Settings()


def off(source, oid, title, price, color="", ram="", stock="IN_STOCK"):
    return enrich(Offer(source, oid, title, price, "toman", stock=stock, raw_color=color, raw_ram=ram, fetched_at=""), ex)


def _labels(items):
    from pricecompare.pricing import product_label
    return sorted(product_label(w) for w in items)


def test_light_blue_and_blue_are_one_colour():
    assert {ex.color_of(x, explicit=True) for x in ("آبی", "آبی روشن", "ابی", "Light Blue", "Mist Blue")} == {"blue"}
    assert ex.color_of("آبی تیره", explicit=True) == "dark blue"                  # dark blue stays a different colour


def test_clusters_join_across_shops_and_never_merge_different_models():
    offers = [
        off("eways", "1", "گوشی موبایل Apple مدل iPhone 17 Non Active CHA ظرفیت 256GB - سبز", 349e6, ram="8"),
        off("hamrahtel", "2", "iPhone 17 256GB CH/A Non Active", 348.99e6, color="Mist Blue"),
        off("hamrahtel", "3", "iPhone 17 Pro Max 256GB ZA/A Non Active", 539e6, color="Silver"),
        off("eways", "4", "گوشی موبایل Xiaomi مدل Redmi A3 (RAM 4) ظرفیت 128GB - آبی روشن", 34.5e6),
        off("hamrahtel", "5", "Redmi A3 128GB RAM 4GB", 34.09e6, color="ابی"),
        off("hamrahtel", "6", "Galaxy A17 128GB RAM 4GB Vietnam", 47.3e6, color="مشکی"),
        off("hamrahtel", "7", "Galaxy A17 128GB RAM 6GB Vietnam", 56.5e6, color="مشکی"),
        off("hamrahtel", "8", "NOKIA 106 FA مونتاژ ایران", 3e6, color="مشکی"),
    ]
    items, _, _ = discover(offers, ex, st, Discovery(enabled=True))
    names = _labels(items)
    assert "iPhone 17 256GB CH/A Non Active" in names                                 # eways + hamrahtel joined
    assert any(n.startswith("iPhone 17 Pro Max") for n in names)                    # different product
    assert sum(n.startswith("Redmi A3") for n in names) == 1                         # eways + hamrahtel = ONE product
    assert sum(n.startswith("Galaxy A17") for n in names) == 2                       # 4GB and 6GB stay apart
    assert sum(n.startswith("iPhone 17 ") and "Pro" not in n for n in names) == 1


def test_malformed_persian_title_noise_does_not_leak_into_discovery_labels():
    offers = [
        off("farnaa", "1", "iPhone 17 Not دوسیم و پارت نامبر 256GB CH/A Active", 350e6),
        off("farnaa", "2", "iPhone 17 Not شده Pro Max 256GB ZA/A Active", 540e6),
        off("farnaa", "3", "iPhone 17 Not و پارت نامبر Pro 256GB ZA/A Active", 472e6),
        off("farnaa", "4", "iPhone 17 دوسیم Not شده Pro Max 512GB ZA/A Active", 580e6),
    ]
    items, _, _ = discover(offers, ex, st, Discovery(enabled=True))
    labels = _labels(items)
    assert "iPhone 17 256GB CH/A Non Active" in labels
    assert "iPhone 17 Pro Max 256GB ZA/A Non Active" in labels
    assert "iPhone 17 Pro 256GB ZA/A Non Active" in labels
    assert "iPhone 17 Pro Max 512GB ZA/A Non Active" in labels
    assert not any("د" in label or "و" in label or "شده" in label for label in labels)


def test_known_regions_never_share_a_product_but_unknown_is_a_wildcard():
    offers = [off("a", "1", "iPhone 17 256GB CH/A Non Active", 1e8, color="Black"),
              off("b", "2", "iPhone 17 256GB ZA/A Non Active", 1e8, color="Black"),
              off("c", "3", "آیفون 17 256 گیگ مشکی", 1e8)]
    items, _, members = discover(offers, ex, st, Discovery(enabled=True))
    assert len(items) == 2                                                            # CH/A and ZA/A apart; unknown joined one


def _write_watchlist(tmp_path, data):
    (tmp_path / "config" / "watchlist.yaml").write_text(yaml.safe_dump(data, allow_unicode=True), encoding="utf-8")


def _run(tmp_path, wl, **kw):
    cfg, base = make_project(tmp_path, **kw)
    _write_watchlist(tmp_path, wl)
    return run(cfg, base_dir=base)


def _by_label(res):
    return {p["label"]: p for p in res.doc["products"]}


def test_discovery_prices_every_phone_per_colour_with_lowest_price(tmp_path):
    res = _run(tmp_path, {"products": [], "discovery": {"enabled": True}})
    assert res.exit_code == 0
    prods = _by_label(res)
    ip = {v["variant"]: (v["winner"]["source"], v["winner"]["price_toman"]) for v in prods["iPhone 17 256GB CH/A"]["variants"]}
    assert ip == {"black": ("shop_a", 64_900_000), "blue": ("shop_b", 64_100_000)}    # lowest per colour across 3 shops
    for label in ("iPhone 17 Pro 256GB CH/A", "iPhone 17 Pro Max 256GB", "iPhone 17 Air 256GB", "iPhone 17e 256GB"):
        assert label in prods, (label, sorted(prods))                                 # the traps are separate products
    assert res.summary["products_discovered"] == len(prods) > 8
    assert all(p["origin"] == "discovered" for p in prods.values())


def test_explicit_watchlist_wins_and_is_not_duplicated(tmp_path):
    wl = {"products": [{"id": "ip17", "brand": "apple", "model": "iPhone 17", "storage": 256}], "discovery": {"enabled": True}}
    res = _run(tmp_path, wl)
    origins = [(p["label"], p["origin"]) for p in res.doc["products"]]
    assert origins.count(("iPhone 17 256GB", "watchlist")) == 1 and not any(l.startswith("iPhone 17 256GB") and o == "discovered" for l, o in origins)


def test_min_sources_brands_and_exclude_filters(tmp_path):
    res = _run(tmp_path / "a", {"products": [], "discovery": {"enabled": True, "min_sources": 2}})
    assert res.doc["products"] and all(len({o["source"] for v in p["variants"] for o in v["offers"] if o["valid"]}) >= 2 for p in res.doc["products"])
    res = _run(tmp_path / "b", {"products": [], "discovery": {"enabled": True, "brands": ["xiaomi"]}})
    assert res.doc["products"] and {p["brand"] for p in res.doc["products"]} == {"xiaomi"}
    res = _run(tmp_path / "c", {"products": [], "discovery": {"enabled": True, "exclude_regex": "Redmi"}})
    assert not any("Redmi" in p["label"] for p in res.doc["products"])


def test_discovery_config_validation(tmp_path):
    for wl in ({"products": [], "discovery": {"enabled": True, "min_sourcess": 2}}, {"products": [], "discovery": {"enabled": True, "min_sources": 0}},
               {"products": []}):
        assert _run(tmp_path / str(abs(hash(str(wl)))), wl).exit_code == 4


# ---------------- Telegram posts ----------------
def _doc(tmp_path, **kw):
    res = _run(tmp_path, {"products": [], "discovery": {"enabled": True}})
    return res.doc


def test_posts_are_split_by_brand_product_or_not_at_all(tmp_path):
    doc = _doc(tmp_path)
    by_brand = build_telegram_messages(doc, "brand")
    assert by_brand[0].startswith("📊") and any(m.startswith("━━ 🍎 Apple") for m in by_brand) and any("Samsung" in m.split("\n")[0] for m in by_brand)
    n_products = sum(1 for p in doc["products"] if any(v["winner"] for v in p["variants"]))
    assert len(build_telegram_messages(doc, "product")) == 1 + n_products
    assert len(build_telegram_messages(doc, "none")) == 2
    text = "\n".join(by_brand)
    assert "##" not in text and "**" not in text and "🏆" in text


def test_changes_only_and_generic_links(tmp_path):
    doc = _doc(tmp_path)
    key = history.key("iphone-17-256gb-x", "blue")
    prod = next(p for p in doc["products"] if p["label"] == "iPhone 17 256GB CH/A")
    key = history.key(prod["id"], "blue")
    msgs = build_telegram_messages(doc, "brand", changes={key: 70_000_000}, removed=[])
    body = "\n".join(msgs)
    assert "فقط تغییرات" in body and "▼ قبلاً 70,000,000" in body and "Galaxy" not in body and "black:" not in body
    new = "\n".join(build_telegram_messages(doc, "brand", changes={key: None}, removed=[]))
    assert "🆕" in new
    for p in doc["products"]:                                            # 3+ lines sharing one URL -> no link noise
        for v in p["variants"]:
            if v["winner"]:
                v["winner"]["url"] = "https://shop.example/category"
    assert "🔗" not in "\n".join(build_telegram_messages(doc, "brand"))


def test_send_accepts_many_messages_and_caps_them():
    parts = telegram.send("t", "c", ["a\nb", "c" * 50, "d"], limit=20, dry_run=True)
    assert parts[0] == "a\nb" and len(parts) >= 4
    capped = telegram.send("t", "c", [str(i) for i in range(30)], limit=20, dry_run=True, max_messages=5)
    assert len(capped) == 5 and "telegram_max_messages" in capped[-1]


def test_changed_keys_rules():
    last = {"a|x": {"price": 100.0, "source": "s1"}, "b|x": {"price": 100.0, "source": "s1"}, "gone|x": {"price": 5.0, "source": "s1"}}
    cur = {"a|x": {"price": 100.2, "source": "s2"}, "b|x": {"price": 90.0, "source": "s1"}, "new|x": {"price": 7.0, "source": "s1"}}
    changed, removed = history.changed_keys(cur, last, 0.5)
    assert changed == {"b|x": 100.0, "new|x": None} and removed == ["gone|x"]       # 0.2% and a source swap are noise


def test_group_settings_are_validated(tmp_path):
    from pricecompare.config import ConfigError, load_settings
    for bad in ({"telegram_group_by": "colour"}, {"telegram_mode": "sometimes"}):
        cfg, _ = make_project(tmp_path / str(len(bad)) / next(iter(bad)), settings=bad)
        try:
            load_settings(cfg)
        except ConfigError:
            continue
        raise AssertionError(bad)
