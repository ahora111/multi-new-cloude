"""Golden set: every NEGATIVE pair must never match; every POSITIVE pair must AUTO-match."""
from pricecompare.config import Settings
from pricecompare.extract import Extractor
from pricecompare.matcher import evaluate, AUTO, NO_MATCH
from pricecompare.models import Offer, WatchItem
from pricecompare.runner import enrich

ex, st = Extractor(), Settings()


def _status(title, wmodel, brand, **kw):
    w = WatchItem(id="w", brand=brand, model=wmodel, **kw)
    o = enrich(Offer("s", "1", title, 1e7, "toman"), ex)
    return evaluate(o, w, ex.parse(wmodel), st).status


POSITIVE = [  # (offer title, watch model, brand, kwargs)
    ("Apple iPhone 17 256GB Blue", "iPhone 17", "apple", {"storage_gb": 256}),
    ("گوشی موبایل اپل مدل iPhone 17 ظرفیت 256 گیگابایت - آبی", "iPhone 17", "apple", {"storage_gb": 256}),
    ("آیفون 17 256 گیگ مشکی", "iPhone 17", "apple", {"storage_gb": 256}),
    ("iPhone 17 256GB CH/A Non Active", "iPhone 17", "apple", {"storage_gb": 256, "region": "cha", "condition": "nonactive"}),
    ("iPhone 17 Not دوسیم و پارت نامبر 256GB CH/A Active", "iPhone 17", "apple", {"storage_gb": 256, "region": "cha", "condition": "nonactive"}),
    ("iPhone 17 Not شده Pro Max 256GB ZA/A Active", "iPhone 17 Pro Max", "apple", {"storage_gb": 256, "region": "singapore", "condition": "nonactive"}),
    ("iPhone 17 Not و پارت نامبر Pro 256GB ZA/A Active", "iPhone 17 Pro", "apple", {"storage_gb": 256, "region": "singapore", "condition": "nonactive"}),
    ("iPhone 17 دوسیم Not شده Pro Max 512GB ZA/A Active", "iPhone 17 Pro Max", "apple", {"storage_gb": 512, "region": "singapore", "condition": "nonactive"}),
    ("iPhone 17 256GB CHA NonActive", "iPhone 17", "apple", {"storage_gb": 256, "region": "cha", "condition": "nonactive"}),
    ("Apple iPhone 17 Pro 256GB Silver", "iPhone 17 Pro", "apple", {"storage_gb": 256}),
    ("آیفون 17 پرو 256 گیگ نقره ای", "iPhone 17 Pro", "apple", {"storage_gb": 256}),
    ("Apple iPhone 17 Pro Max 1TB", "iPhone 17 Pro Max", "apple", {"storage_gb": 1024}),
    ("Apple iPhone 17 Air 256GB", "iPhone 17 Air", "apple", {"storage_gb": 256}),
    ("Apple iPhone 17e 256GB", "iPhone 17e", "apple", {"storage_gb": 256}),
    ("Samsung Galaxy A17 4G 128GB RAM 4GB", "Galaxy A17 4G", "samsung", {"storage_gb": 128, "ram_gb": 4}),
    ("گوشی سامسونگ گلکسی A17 (RAM 4) ظرفیت 128 گیگ 4G مشکی", "Galaxy A17 4G", "samsung", {"storage_gb": 128, "ram_gb": 4}),
    ("Galaxy A17 5G 128GB", "Galaxy A17 5G", "samsung", {"storage_gb": 128}),
    ("Samsung Galaxy S25 Ultra 512GB", "Galaxy S25 Ultra", "samsung", {"storage_gb": 512}),
    ("Samsung Galaxy S25+ 256GB", "Galaxy S25 Plus", "samsung", {"storage_gb": 256}),
    ("Samsung Galaxy S25 FE 256GB", "Galaxy S25 FE", "samsung", {"storage_gb": 256}),
    ("Xiaomi Redmi Note 14 256GB RAM 8GB", "Redmi Note 14", "xiaomi", {"storage_gb": 256, "ram_gb": 8}),
    ("ردمی نوت 14 8/256 مشکی", "Redmi Note 14", "xiaomi", {"storage_gb": 256, "ram_gb": 8}),
    ("Xiaomi Redmi Note 14 Pro 256GB RAM 8GB", "Redmi Note 14 Pro", "xiaomi", {"storage_gb": 256, "ram_gb": 8}),
    ("Google Pixel 10 Pro 256GB", "Pixel 10 Pro", "google", {"storage_gb": 256}),
    ("Samsung Galaxy A07 128GB", "Galaxy A07", "samsung", {"storage_gb": 128}),
    ("iPhone 17 256GB", "iPhone 17", "apple", {"storage_gb": 256, "ram_gb": 8}),   # RAM absent in offer is fine
]
NEGATIVE = [
    ("Apple iPhone 17 Pro 256GB", "iPhone 17", "apple", {"storage_gb": 256}),
    ("Apple iPhone 17 Pro Max 256GB", "iPhone 17 Pro", "apple", {"storage_gb": 256}),
    ("Apple iPhone 17 Air 256GB", "iPhone 17", "apple", {"storage_gb": 256}),
    ("Apple iPhone 17e 256GB", "iPhone 17", "apple", {"storage_gb": 256}),
    ("Apple iPhone 17 256GB", "iPhone 17 Pro", "apple", {"storage_gb": 256}),
    ("Apple iPhone 17 512GB", "iPhone 17", "apple", {"storage_gb": 256}),
    ("Apple iPhone 16 256GB", "iPhone 17", "apple", {"storage_gb": 256}),
    ("Apple iPhone 17 256GB Vietnam", "iPhone 17", "apple", {"storage_gb": 256, "region": "cha"}),
    ("Apple iPhone 17 256GB Active", "iPhone 17", "apple", {"storage_gb": 256, "condition": "nonactive"}),
    ("Samsung Galaxy A17 5G 128GB RAM 4GB", "Galaxy A17 4G", "samsung", {"storage_gb": 128}),
    ("Samsung Galaxy A17 4G 128GB RAM 6GB", "Galaxy A17 4G", "samsung", {"storage_gb": 128, "ram_gb": 4}),
    ("Samsung Galaxy A17 4G 256GB RAM 4GB", "Galaxy A17 4G", "samsung", {"storage_gb": 128}),
    ("Samsung Galaxy A07 128GB", "Galaxy A17", "samsung", {"storage_gb": 128}),
    ("Samsung Galaxy S25 Ultra 256GB", "Galaxy S25", "samsung", {"storage_gb": 256}),
    ("Samsung Galaxy S25 FE 256GB", "Galaxy S25", "samsung", {"storage_gb": 256}),
    ("Samsung Galaxy S25 256GB", "Galaxy S25 Plus", "samsung", {"storage_gb": 256}),
    ("Samsung Galaxy S25+ 256GB", "Galaxy S25 Ultra", "samsung", {"storage_gb": 256}),
    ("Xiaomi Redmi Note 14 Pro 256GB RAM 8GB", "Redmi Note 14", "xiaomi", {"storage_gb": 256}),
    ("Xiaomi Redmi Note 14 256GB RAM 8GB", "Redmi Note 14 Pro", "xiaomi", {"storage_gb": 256}),
    ("Xiaomi Redmi Note 14S 256GB", "Redmi Note 14", "xiaomi", {"storage_gb": 256}),
    ("Xiaomi Redmi 14 256GB", "Redmi Note 14", "xiaomi", {"storage_gb": 256}),
    ("Xiaomi Redmi Note 13 256GB", "Redmi Note 14", "xiaomi", {"storage_gb": 256}),
    ("Samsung Galaxy A17 128GB", "iPhone 17", "apple", {"storage_gb": 128}),
    ("Google Pixel 10 256GB", "Pixel 10 Pro", "google", {"storage_gb": 256}),
    ("Google Pixel 10 Pro XL 256GB", "Pixel 10 Pro", "google", {}),
    ("Apple iPhone 17 Pro Max 256GB Silver", "iPhone 17", "apple", {"storage_gb": 256}),
    ("Apple iPhone 17 Plus 256GB", "iPhone 17", "apple", {"storage_gb": 256}),
    ("Samsung Galaxy Z Fold 7 512GB", "Galaxy Z Flip 7", "samsung", {"storage_gb": 512}),
    ("Samsung Galaxy A17 Lite 128GB", "Galaxy A17", "samsung", {"storage_gb": 128}),
    ("Xiaomi Poco X7 256GB", "Redmi Note 14", "xiaomi", {"storage_gb": 256}),
    ("Apple iPhone 17 Mini 256GB", "iPhone 17", "apple", {"storage_gb": 256}),
]


def test_golden_positive_pairs_auto_match():
    bad = [(t, w) for t, w, b, kw in POSITIVE if _status(t, w, b, **kw) != AUTO]
    assert not bad, bad


def test_golden_negative_pairs_never_match():
    bad = [(t, w) for t, w, b, kw in NEGATIVE if _status(t, w, b, **kw) != NO_MATCH]
    assert not bad, bad


def test_golden_size_and_balance():
    assert len(POSITIVE) + len(NEGATIVE) >= 50 and len(NEGATIVE) >= 25


def test_missing_required_attribute_goes_to_review_not_match():
    assert _status("Apple iPhone 17 Blue", "iPhone 17", "apple", storage_gb=256) == "REVIEW"
    assert _status("Apple iPhone 17 256GB", "iPhone 17", "apple", storage_gb=256, region="cha") == "REVIEW"


def test_fuzzy_never_overrides_number_mismatch_and_thresholds_are_used():
    from pricecompare.config import Settings as S
    strict = S(match_auto_threshold=99.0, match_review_threshold=98.0)
    w = WatchItem(id="w", brand="samsung", model="Galaxy A17", storage_gb=128)
    o = enrich(Offer("s", "1", "Samsung Galaxy Aa17 128GB", 1e7, "toman"), ex)   # near-typo of a17
    assert evaluate(o, w, ex.parse("Galaxy A17"), S()).status in ("REVIEW", "NO_MATCH")
    assert evaluate(o, w, ex.parse("Galaxy A17"), strict).status == "NO_MATCH"


def test_barcode_is_definitive():
    w = WatchItem(id="w", brand="apple", model="iPhone 17", barcodes=["1234567890123"])
    o = enrich(Offer("s", "1", "کالای عجیب بدون اسم", 1e7, "toman", extra={"barcode": "1234567890123"}), ex)
    assert evaluate(o, w, ex.parse("iPhone 17"), st).status == AUTO
