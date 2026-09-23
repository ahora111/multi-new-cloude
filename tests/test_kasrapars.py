from pathlib import Path
import yaml

from conftest_helpers import ROOT, make_project
from pricecompare.config import SourceConfig
from pricecompare.extract import Extractor
from pricecompare.runner import enrich, run
from pricecompare.sources import build_source
from pricecompare.sources.kasrapars import parse_kasrapars_html

FIXTURE = ROOT / "fixtures" / "kasrapars_mobile.html"


def _cfg(**opts):
    return SourceConfig("kasrapars", "kasrapars", "toman", min_expected_products=1, options=opts)


def test_kasrapars_fixture_extracts_sale_price_id_url_stock_image_and_fields():
    rows = parse_kasrapars_html(FIXTURE.read_text(encoding="utf-8"), "https://plus.kasrapars.ir/")
    r = next(x for x in rows if x["id"] == "KP-A56-8256-BLK")
    assert r["price"] == "۱۰۷٬۳۹۰٬۰۰۰ تومان"
    assert r["stock"] == "in_stock"
    assert r["url"].endswith("/product/samsung-galaxy-a56-5g-8256-black")
    assert r["image"].endswith("a56-black.webp")
    assert r["color"] == "مشکی"
    assert r["extra"]["sku"] == "KP-A56-8256-BLK"


def test_kasrapars_old_price_is_metadata_and_sale_price_is_offer_price():
    rows = parse_kasrapars_html(FIXTURE.read_text(encoding="utf-8"), "https://plus.kasrapars.ir/")
    r = next(x for x in rows if x["id"] == "KP-A56-8256-BLK" and x["color"] == "مشکی")
    assert r["price"] == "۱۰۷٬۳۹۰٬۰۰۰ تومان"
    assert r["extra"]["old_price"] == 110_000_000


def test_kasrapars_out_of_stock_is_not_in_stock():
    rows = parse_kasrapars_html(FIXTURE.read_text(encoding="utf-8"), "https://plus.kasrapars.ir/")
    r = next(x for x in rows if x["id"] == "KP-A55-8256-BLK")
    assert r["stock"] == "out_of_stock"


def test_kasrapars_source_uses_normal_offer_contract():
    cfg = _cfg(path="fixtures/kasrapars_mobile.html", base_url="https://plus.kasrapars.ir/", follow_next=False)
    offers = build_source(cfg, base_dir=str(ROOT)).fetch([])
    assert len(offers) == 3
    assert all(o.currency_unit_raw == "toman" for o in offers)
    assert {o.stock for o in offers} == {"IN_STOCK", "OUT_OF_STOCK"}


def test_kasrapars_pagination_stops_on_empty_page_and_dedupes(monkeypatch):
    first = FIXTURE.read_text(encoding="utf-8").replace(
        "</body></html>",
        "<a rel=\"next\" href=\"/search/category-mobilephone?brand_slug%5Bxiaomi%5D=false&page=2\">بعدی</a></body></html>",
    )
    pages = {
        "https://plus.kasrapars.ir/search/category-mobilephone?brand_slug%5Bxiaomi%5D=false": first,
        "https://plus.kasrapars.ir/search/category-mobilephone?brand_slug%5Bxiaomi%5D=false&page=2": """
        <html><body>
          <article class='product-card' data-product-id='kp-s26-12256' data-sku='KP-S26-12256-BLK'>
            <a class='product-title' href='/product/s26'>Samsung Galaxy S26 Ultra 12GB 256GB Black</a>
            <span class='sale-price'>۳۴۰٬۹۹۹٬۰۰۰ تومان</span><span class='stock'>موجود</span>
          </article>
          <a rel='next' href='/search/category-mobilephone?brand_slug%5Bxiaomi%5D=false&page=3'>بعدی</a>
        </body></html>
        """,
        "https://plus.kasrapars.ir/search/category-mobilephone?brand_slug%5Bxiaomi%5D=false&page=3": "<html><body><p>empty</p></body></html>",
    }
    src = build_source(_cfg(url=list(pages)[0], base_url="https://plus.kasrapars.ir/", max_pages=100), base_dir=str(ROOT))
    monkeypatch.setattr(src, "read", lambda u: pages[u])
    rows = src.records([])
    assert src.raw_count == 4
    assert len(rows) == 4


def test_kasrapars_central_brand_and_color_matching(tmp_path):
    srcs = [
        {"name":"kasrapars","type":"kasrapars","currency_unit":"toman","priority":50,"min_expected_products":1,"path":"fixtures/kasrapars_mobile.html","follow_next":False},
        {"name":"eways","type":"csv","currency_unit":"toman","priority":10,"min_expected_products":1,"path":"fixtures/e.csv","columns":{"id":"sku","title":"title","price":"price","stock":"stock","url":"link"}},
    ]
    cfg, base = make_project(tmp_path, sources=srcs, watchlist=[{"id":"a56","brand":"samsung","model":"Galaxy A56","storage":256,"ram":8}])
    (Path(base)/"fixtures/e.csv").write_text("sku,title,price,stock,link\ne1,Samsung Galaxy A56 5G 8GB 256GB Black,106000000,موجود,https://e/1\n", encoding="utf-8")
    res = run(cfg, base_dir=base)
    assert res.exit_code == 0
    p = res.doc["products"][0]
    black = next(v for v in p["variants"] if v["variant"] == "black")
    assert {o["source"] for o in black["offers"]} == {"kasrapars", "eways"}
    assert black["winner"]["source"] == "eways"
    assert {v["variant"] for v in p["variants"]} == {"black", "purple"}


def test_kasrapars_parser_never_invents_missing_fields():
    rows = parse_kasrapars_html("""
    <article class='product-card' data-product-id='x1'>
      <a class='product-title' href='/product/x1'>Samsung Galaxy A56 256GB</a>
      <span class='price'>۱۰۰٬۰۰۰٬۰۰۰</span>
    </article>
    """, "https://plus.kasrapars.ir/")
    r = rows[0]
    assert r["color"] == ""
    assert r["brand"] == ""
    assert r["storage"] == ""
    assert r["ram"] == ""


def test_kasrapars_browser_api_payload_flattens_parent_product_and_variant():
    payload = {
        "products": [{
            "id": "kp-api-1",
            "name": "Samsung Galaxy A56 5G 8GB 256GB",
            "url": "/product/a56-api",
            "brand": "Samsung",
            "variants": [{
                "sku": "KP-API-A56-BLK",
                "color": "Black",
                "price": "107390000",
                "stock": "موجود",
            }],
        }]
    }
    from pricecompare.sources.kasrapars import _json_response_records
    rows = _json_response_records(payload, "https://plus.kasrapars.ir/api/products")
    assert len(rows) == 1
    assert rows[0]["id"] == "KP-API-A56-BLK"
    assert rows[0]["title"] == "Samsung Galaxy A56 5G 8GB 256GB"
    assert rows[0]["color"] == "Black"
    assert rows[0]["brand"] == "Samsung"
