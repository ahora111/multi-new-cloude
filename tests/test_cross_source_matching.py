"""Regression tests for the 2026-09-30 production split report.

One physical product (iPhone 17 256GB CH/A Non Active) was shown as three
separate Telegram products because:

* KasraPars titles write storage bare + RAM with unit ("iPhone 17 256 8GB") --
  the parser took 8GB as storage and left "256" inside the model name.
* Farnaa's Persian SEO title has "نات اکتیو" (→ parsed as plain "active")
  and a bare "CH" region code (→ kept as a model token "ch").

The same shorthand also split the Pro Max (kasrapars "256 ... 12GB").
"""
from pricecompare.discovery import discover, display_name
from pricecompare.extract import Extractor
from pricecompare.models import Offer

ex = Extractor()

SETTINGS = type("S", (), {"match_auto_threshold": 95, "match_review_threshold": 85})()
CFG = type("C", (), {"enabled": True, "brands": [], "exclude_regex": "", "min_sources": 1})()


def _offer(source, oid, title, price=1_000_000, color=""):
    return Offer(source=source, source_offer_id=oid, raw_title=title, price_raw=price,
                 currency_unit_raw="toman", stock="IN_STOCK", url="", raw_color=color)


def test_kasrapars_bare_storage_and_ram_with_unit():
    a = ex.parse("iPhone 17 256 8GB CH/A Non Active")
    assert (a.brand, a.core, a.storage_gb, a.ram_gb) == ("apple", ["iphone", "17"], 256, 8)
    b = ex.parse("iPhone 17 256 Single + Esim Pro Max 12GB ZA/A Non Active")
    assert (b.core, b.tiers, b.storage_gb, b.ram_gb) == (["iphone", "17"], ["max", "pro"], 256, 12)
    assert "+" not in b.core and "single" not in b.core and "esim" not in b.core


def test_farnaa_persian_title_parses_like_the_english_one():
    fa = "گوشی موبایل اپل مدل iPhone 17 CH دو سیم کارت ظرفیت 256 گیگابایت و رم 8 گیگابایت نات اکتیو"
    en = "Apple iPhone 17 Not Active Dual SIM 256GB 8GB RAM Part Number CHA"
    a, b = ex.parse(fa), ex.parse(en)
    for x in (a, b):
        assert x.brand == "apple" and x.core == ["iphone", "17"]
        assert x.storage_gb == 256 and x.ram_gb == 8
        assert x.region == "cha" and x.condition == "nonactive"


def test_bare_region_codes_ch_and_za_are_recognised():
    assert ex.parse("iPhone 17 CH 256GB").region == "cha"
    assert ex.parse("iPhone 17 ZA 256GB").region == "singapore"
    # but model numbers never become regions
    assert ex.parse("iPhone 17e 256GB").core == ["iphone", "17e"]


def test_ram_class_model_numbers_are_never_eaten():
    assert ex.parse("iPhone 12 256GB CH/A Non Active").core == ["iphone", "12"]
    assert ex.parse("iPhone 8 64GB").core == ["iphone", "8"] and ex.parse("iPhone 8 64GB").storage_gb == 64
    assert ex.parse("iPhone 16 512GB ZA/A Non Active").core == ["iphone", "16"]
    # bare storage without any unit still lands on the right attribute
    assert ex.parse("iPhone 17 256").storage_gb == 256 and ex.parse("iPhone 17 256").core == ["iphone", "17"]


def test_all_four_sources_cluster_into_one_product():
    """The exact production titles must end up in ONE discovery cluster per model."""
    offers = [
        _offer("kasrapars", "k1", "iPhone 17 256 8GB CH/A Non Active", color="black"),
        _offer("kasrapars", "k2", "iPhone 17 256 8GB CH/A Non Active", color="blue"),
        _offer("hamrahtel", "h1", "iPhone 17 256GB CH/A Non Active", color="black"),
        _offer("eways", "e1", "iPhone 17 256GB CH/A Non Active", color="white"),
        _offer("farnaa", "f1", "گوشی موبایل اپل مدل iPhone 17 CH دو سیم کارت ظرفیت 256 گیگابایت و رم 8 گیگابایت نات اکتیو", color="purple"),
        _offer("farnaa", "f2", "Apple iPhone 17 Not Active Dual SIM 256GB 8GB RAM Part Number CHA", color="white"),
        # the Pro Max pair (kasrapars shorthand vs hamrahtel unit-complete)
        _offer("kasrapars", "k3", "iPhone 17 256 Single + Esim Pro Max 12GB ZA/A Non Active", color="deep_blue"),
        _offer("hamrahtel", "h2", "iPhone 17 Pro Max 256GB 12GB ZA/A Non Active", color="orange"),
    ]
    for o in offers:
        a = ex.parse(o.raw_title)
        o.brand, o.model_core, o.tiers = a.brand, a.core, a.tiers
        o.storage_gb, o.ram_gb, o.color = a.storage_gb, a.ram_gb, o.raw_color or a.color
        o.region, o.network, o.condition = a.region, a.network, a.condition
        o.price_toman = o.price_raw

    items, attrs, members = discover(offers, ex, SETTINGS, CFG)
    by_model = {}
    for w in items:
        key = (w.brand, w.model, w.storage_gb, w.region, w.condition)
        by_model.setdefault(key, []).extend(members[w.id])

    iphone17 = [k for k in by_model if k[1].startswith("iPhone 17") and "Pro" not in k[1]]
    promax = [k for k in by_model if k[1].startswith("iPhone 17") and "Pro" in k[1]]
    assert len(iphone17) == 1, f"iPhone 17 still split: {iphone17}"
    assert len(promax) == 1, f"Pro Max still split: {promax}"

    k17 = by_model[iphone17[0]]
    assert {o.source for o in k17} == {"kasrapars", "hamrahtel", "eways", "farnaa"}
    kpm = by_model[promax[0]]
    assert {o.source for o in kpm} == {"kasrapars", "hamrahtel"}

    w17 = next(w for w in items if w.model.startswith("iPhone 17") and "Pro" not in w.model)
    assert display_name(attrs[w17.id].core, attrs[w17.id].tiers, attrs[w17.id].network) == "iPhone 17"


def test_labels_no_longer_leak_shorthand():
    from pricecompare.pricing import product_label
    offers = [
        _offer("kasrapars", "k1", "iPhone 17 256 8GB CH/A Non Active"),
        _offer("hamrahtel", "h1", "iPhone 17 256GB CH/A Non Active"),
    ]
    for o in offers:
        a = ex.parse(o.raw_title)
        o.brand, o.model_core, o.tiers = a.brand, a.core, a.tiers
        o.storage_gb, o.ram_gb, o.color = a.storage_gb, a.ram_gb, a.color
        o.region, o.network, o.condition = a.region, a.network, a.condition
        o.price_toman = o.price_raw
    items, attrs, members = discover(offers, ex, SETTINGS, CFG)
    w = items[0]
    w.region = "cha"
    w.condition = "nonactive"
    assert product_label(w) == "iPhone 17 256GB CH/A Non Active"
