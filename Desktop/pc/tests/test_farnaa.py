from pathlib import Path

from pricecompare.config import SourceConfig
from pricecompare.sources import build_source
from pricecompare.sources.farnaa import parse_farnaa_html

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "fixtures" / "farnaa_mobile.html"


def test_farnaa_fixture_has_large_catalog_and_stable_ids():
    html = FIXTURE.read_text(encoding="utf-8")
    records = parse_farnaa_html(html)
    assert len(records) >= 400
    assert all(r["id"] for r in records)
    assert len({r["id"] for r in records}) == len(records)


def test_farnaa_extracts_price_stock_url_image_and_variant():
    html = FIXTURE.read_text(encoding="utf-8")
    records = parse_farnaa_html(html)
    r = next(x for x in records if x["id"] == "10099:10457")
    assert r["price"] == 1_274_000
    assert r["stock"] == "in stock"
    assert r["color"] == "خاکستری"
    assert r["url"] == "https://farnaa.com/product/10099/mobile/nokia-106-(2018)-dual-sim-mobile-phone"
    assert r["image"].startswith("https://media.farnaa.com/")
    assert r["extra"]["variant_id"] == "10457"


def test_farnaa_out_of_stock_zero_price_is_none_not_zero():
    html = FIXTURE.read_text(encoding="utf-8")
    records = parse_farnaa_html(html)
    r = next(x for x in records if x["id"] == "10101")
    assert r["price"] is None
    assert r["stock"] == "out of stock"


def test_farnaa_source_uses_normal_core_offer_contract():
    cfg = SourceConfig(
        name="farnaa", type="farnaa", currency_unit="toman",
        min_expected_products=50,
        options={"path": "fixtures/farnaa_mobile.html", "base_url": "https://farnaa.com/", "in_stock_values": ["in stock"], "out_of_stock_values": ["out of stock"]},
    )
    offers = build_source(cfg, base_dir=str(ROOT)).fetch([])
    assert len(offers) >= 400
    in_stock = next(o for o in offers if o.source_offer_id == "10099:10457")
    assert in_stock.price_raw == 1_274_000
    assert in_stock.currency_unit_raw == "toman"
    assert in_stock.stock == "IN_STOCK"
