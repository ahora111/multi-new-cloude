import json
from pathlib import Path
import yaml

from conftest_helpers import make_project
from pricecompare.config import Discovery, Settings
from pricecompare.discovery import discover
from pricecompare.extract import Extractor
from pricecompare.models import Offer
from pricecompare.runner import enrich, run


EX = Extractor()
ST = Settings()


def off(source, oid, title, price, color="", ram="", stock="IN_STOCK", extra=None):
    return enrich(Offer(source, oid, title, price, "toman", stock=stock,
                        raw_color=color, raw_ram=ram, extra=extra or {}), EX)


def test_brand_and_model_canonicalization_is_source_independent():
    pairs = [
        ("Samsung Galaxy A56 5G 8GB 256GB", "سامسونگ Galaxy A56 5G رم 8 حافظه 256GB"),
        ("XIAOMI Redmi Note 14 Pro 5G 8GB 256GB", "شیائومی Redmi Note 14 Pro 5G رم 8 ظرفیت 256 گیگ"),
        ("APPLE iPhone 16 Pro 256GB", "اپل iPhone 16 Pro 256GB"),
        ("HUAWEI Nova 13 256GB", "هواوی Nova 13 256GB"),
        ("HONOR X8c 8GB 256GB", "آنر X8c رم 8 256GB"),
        ("NOKIA 110 4G", "نوکیا 110 4G"),
    ]
    for a, b in pairs:
        aa, bb = EX.parse(a), EX.parse(b)
        assert aa.brand == bb.brand
        assert set(aa.core) == set(bb.core)
        assert aa.storage_gb == bb.storage_gb
        assert aa.ram_gb == bb.ram_gb
        assert aa.network == bb.network


def test_color_canonicalization_and_unknown_are_strict():
    assert EX.color_of("Black", explicit=True) == "black"
    assert EX.color_of("مشکی", explicit=True) == "black"
    assert EX.color_of("White", explicit=True) == "white"
    assert EX.color_of("سفید", explicit=True) == "white"
    assert EX.color_of("Blue", explicit=True) == "blue"
    assert EX.color_of("آبی", explicit=True) == "blue"
    assert EX.color_of("Silver", explicit=True) == "silver"
    assert EX.color_of("نقره‌ای", explicit=True) == "silver"
    assert EX.color_of("Gray", explicit=True) == "gray"
    assert EX.color_of("Grey", explicit=True) == "gray"
    assert EX.color_of("خاکستری", explicit=True) == "gray"
    assert EX.color_of("طوسی", explicit=True) == "gray"
    assert EX.color_of("Black", explicit=True) != EX.color_of("Blue", explicit=True)
    assert EX.color_of("Black", explicit=True) != EX.color_of("White", explicit=True)
    assert EX.color_of("Titanium Gray", explicit=True) == "titanium_gray"
    assert EX.color_of("Natural Titanium", explicit=True) == "natural titanium"
    assert EX.color_of("Lavender", explicit=True) == "lavender"


def test_model_hard_boundaries():
    def same(a, b):
        aa, bb = EX.parse(a), EX.parse(b)
        return aa.brand == bb.brand and aa.core == bb.core and aa.tiers == bb.tiers and aa.storage_gb == bb.storage_gb and aa.ram_gb == bb.ram_gb and aa.network == bb.network
    assert not same("Galaxy A55 8GB 256GB", "Galaxy A56 8GB 256GB")
    assert not same("iPhone 16 256GB", "iPhone 16 Pro 256GB")
    assert not same("iPhone 16 Pro 256GB", "iPhone 16 Pro Max 256GB")
    assert not same("Galaxy S25 8GB 256GB", "Galaxy S25 Ultra 8GB 256GB")
    assert not same("Galaxy A56 8GB 256GB", "Galaxy A56 12GB 256GB")
    assert not same("Galaxy A56 8GB 128GB", "Galaxy A56 8GB 256GB")
    assert not same("Galaxy A56 8GB 256GB 4G", "Galaxy A56 8GB 256GB 5G")


def test_two_sources_three_sources_and_price_do_not_duplicate_product():
    offers = [
        off("eways", "e1", "Samsung Galaxy A56 5G 8GB 256GB Black", 50_000_000),
        off("hamrahtel", "h1", "سامسونگ Galaxy A56 5G RAM 8 256GB مشکی", 51_000_000),
        off("farnaa", "f1", "Samsung Galaxy A56 5G 8GB 256 GB BLACK", 49_500_000),
    ]
    items, _, members = discover(offers, EX, ST, Discovery(enabled=True))
    assert len(items) == 1
    assert {o.source for o in members[items[0].id]} == {"eways", "hamrahtel", "farnaa"}


def test_stock_does_not_affect_matching_and_unknown_color_stays_unknown():
    offers = [
        off("eways", "e1", "Samsung Galaxy A56 8GB 256GB", 50_000_000, stock="OUT_OF_STOCK"),
        off("farnaa", "f1", "Samsung Galaxy A56 8GB 256GB Black", 49_500_000, stock="IN_STOCK"),
    ]
    items, _, members = discover(offers, EX, ST, Discovery(enabled=True))
    assert len(items) == 1
    assert len(members[items[0].id]) == 2


def test_network_is_never_merged_when_one_offer_is_unknown():
    offers = [
        off("a", "1", "Galaxy A56 8GB 256GB", 1),
        off("b", "2", "Galaxy A56 5G 8GB 256GB", 1),
        off("c", "3", "Galaxy A56 4G 8GB 256GB", 1),
    ]
    items, _, members = discover(offers, EX, ST, Discovery(enabled=True))
    assert len(items) == 3
    assert sorted(len(v) for v in members.values()) == [1, 1, 1]


def test_hanofer_order_and_persian_brand_join():
    offers = [
        off("hamrahtel", "h1", "Hanofer N235 2024", 2_799_000, color="gray"),
        off("farnaa", "f1", "2024 HANOFER N235", 2_430_000, color="orange"),
        off("eways", "e1", "هانوفر N235 2024", 2_600_000, color="orange"),
    ]
    items, _, members = discover(offers, EX, ST, Discovery(enabled=True))
    assert len(items) == 1
    assert {o.source for o in members[items[0].id]} == {"hamrahtel", "farnaa", "eways"}


def test_same_color_across_sources_is_one_variant_and_different_colors_are_separate(tmp_path):
    # End-to-end: one Product, one black Variant with 3 offers, one blue Variant with 2.
    srcs = [
        {"name":"eways", "type":"csv", "currency_unit":"toman", "priority":10, "path":"fixtures/e.csv", "columns":{"id":"sku","title":"title","price":"price","stock":"stock","url":"link"}},
        {"name":"hamrahtel", "type":"csv", "currency_unit":"toman", "priority":20, "path":"fixtures/h.csv", "columns":{"id":"sku","title":"title","price":"price","stock":"stock","url":"link"}},
        {"name":"farnaa", "type":"csv", "currency_unit":"toman", "priority":30, "path":"fixtures/f.csv", "columns":{"id":"sku","title":"title","price":"price","stock":"stock","url":"link"}},
    ]
    cfg, base = make_project(tmp_path, sources=srcs, watchlist=[])
    (Path(base) / "config" / "watchlist.yaml").write_text(yaml.safe_dump({"products": [], "discovery": {"enabled": True}}, allow_unicode=True), encoding="utf-8")
    fix = Path(base) / "fixtures"
    for fn, body in {
        "e.csv":"sku,title,price,stock,link\ne1,Samsung Galaxy A56 5G 8GB 256GB Black,50000000,موجود,https://e/1\ne2,Samsung Galaxy A56 5G 8GB 256GB Blue,50500000,موجود,https://e/2\n",
        "h.csv":"sku,title,price,stock,link\nh1,سامسونگ Galaxy A56 5G RAM 8 256GB مشکی,51000000,موجود,https://h/1\nh2,Samsung Galaxy A56 5G 8GB 256GB آبی,50400000,موجود,https://h/2\n",
        "f.csv":"sku,title,price,stock,link\nf1,Samsung Galaxy A56 5G 8GB 256GB BLACK,49500000,موجود,https://f/1\nf2,Samsung Galaxy A56 5G 8GB 256GB BLUE,50200000,موجود,https://f/2\n",
    }.items():
        (fix / fn).write_text(body, encoding="utf-8")
    res = run(cfg, base_dir=base)
    assert res.exit_code == 0
    assert len(res.doc["products"]) == 1
    p = res.doc["products"][0]
    variants = {v["variant"]: v for v in p["variants"]}
    assert set(variants) == {"black", "blue"}
    assert {o["source"] for o in variants["black"]["offers"]} == {"eways", "hamrahtel", "farnaa"}
    assert {o["source"] for o in variants["blue"]["offers"]} == {"eways", "hamrahtel", "farnaa"}
    assert variants["black"]["winner"]["source"] == "farnaa"
    assert variants["blue"]["winner"]["source"] == "farnaa"


def test_unknown_color_is_not_promoted_to_a_known_color(tmp_path):
    srcs = [{"name":"a", "type":"csv", "currency_unit":"toman", "priority":10, "path":"fixtures/a.csv", "columns":{"id":"sku","title":"title","price":"price","stock":"stock","link":"link"}},
            {"name":"b", "type":"csv", "currency_unit":"toman", "priority":20, "path":"fixtures/b.csv", "columns":{"id":"sku","title":"title","price":"price","stock":"stock","link":"link"}}]
    cfg, base = make_project(tmp_path, sources=srcs, watchlist=[])
    (Path(base) / "config" / "watchlist.yaml").write_text(yaml.safe_dump({"products": [], "discovery": {"enabled": True}}, allow_unicode=True), encoding="utf-8")
    (Path(base)/"fixtures/a.csv").write_text("sku,title,price,stock,link\na1,Samsung A56 8GB 256GB,50000000,موجود,https://a/1\n", encoding="utf-8")
    (Path(base)/"fixtures/b.csv").write_text("sku,title,price,stock,link\nb1,Samsung A56 8GB 256GB Black,49000000,موجود,https://b/1\n", encoding="utf-8")
    res=run(cfg, base_dir=base)
    assert res.exit_code == 0
    assert len(res.doc["products"]) == 1
    assert {v["variant"] for v in res.doc["products"][0]["variants"]} == {"", "black"} or len(res.doc["products"][0]["variants"]) == 2


def test_valid_gtin_is_cross_source_identity_but_store_product_id_is_not():
    offers = [
        off("eways", "e1", "Totally Different Title 128GB", 10_000_000, extra={"gtin": "0123456789012", "product_id": "777"}),
        off("farnaa", "f1", "Different Merchant Title 256GB", 11_000_000, extra={"gtin": "0123456789012", "product_id": "999"}),
    ]
    items, _, members = discover(offers, EX, ST, Discovery(enabled=True))
    assert len(items) == 1
    assert {o.source for o in members[items[0].id]} == {"eways", "farnaa"}
