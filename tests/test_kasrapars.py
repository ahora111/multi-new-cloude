import json
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


# ---- KasraPars web API (plus.kasrapars.ir is a Nuxt SPA; HTML has no product cards) ----

def _api_payload():
    return {
        "items": {
            "items": [
                {
                    "id": 2910, "brand_id": 11,
                    "slug": "apple-iphone-17-pro-max-25612gb-zaa-not-active",
                    "product_name": "گوشی موبایل اپل مدل iPhone 17 Pro Max ZA/A ظرفیت 256 گیگابایت رم 12 گیگابایت",
                    "product_name_en": "Apple iPhone 17 Pro Max 256/12GB ZA/A (Single Sim + eSim) - Not Active",
                    "short_name": "Apple iPhone 17 Pro Max 256/12GB ZA/A",
                    "src": "https://cdn.kasratel.ir/Product/2910/x.png",
                    "varieties": [
                        {"id": 11168, "price_main": 5200000000, "price_off": 5200000000,
                         "color": {"color_name": "سرمه‌ای (Deep Blue)", "color_name_en": "Deep Blue"},
                         "status": {"title": "موجود", "can_buy": True},
                         "guarantee": {"short_name": "18ماه گارانتی شرکتی"}, "pack": {"name": "اصلی"}},
                        {"id": 11169, "price_main": 5100000000, "price_off": 5100000000,
                         "color": {"color_name": "نارنجی (Cosmic Orange)"},
                         "status": {"title": "موجود", "can_buy": True}},
                    ],
                },
                {
                    "id": 2911, "brand_id": 11,
                    "slug": "apple-iphone-17-2568gb-cha-not-active",
                    "product_name_en": "Apple iPhone 17 256/8GB CH/A - Not Active",
                    "src": "",
                    "varieties": [
                        {"id": 11170, "price_main": 3600000000, "price_off": 3510000000,
                         "color": None, "status": {"title": "ناموجود", "can_buy": False}},
                    ],
                },
            ],
            "_links": {"self": {"href": "https://api.kasrapars.ir/api/web/v10/product/index-brand?page=1"},
                       "next": {"href": "https://api.kasrapars.ir/api/web/v10/product/index-brand?page=2"}},
            "_meta": {"totalCount": 73, "pageCount": 4, "currentPage": 1, "perPage": 20},
        },
        "filters": {"brands": [{"id": 11, "brand_name_en": "apple", "brand_name": "اپل"}]},
    }


def _api_cfg(**opts):
    base = {"base_url": "https://plus.kasrapars.ir/", "follow_next": False,
            "url": "https://api.kasrapars.ir/api/web/v10/product/index-brand?page=1"}
    base.update(opts)
    return SourceConfig("kasrapars", "kasrapars", "rial", min_expected_products=1, options=base)


def test_kasrapars_api_payload_maps_varieties_and_next_link():
    src = build_source(_api_cfg(), base_dir=str(ROOT))
    rows, nxt = src._api_rows(_api_payload())
    assert len(rows) == 3 and nxt.endswith("page=2")
    r0 = rows[0]
    assert r0["id"] == "11168"                                   # variant-level identity
    assert r0["title"].startswith("Apple iPhone 17 Pro Max")
    assert r0["price"] == 5200000000                             # raw RIAL, no conversion here
    assert "سرمه" in r0["color"]
    assert r0["stock"] == "موجود"
    assert r0["url"] == "https://plus.kasrapars.ir/product/apple-iphone-17-pro-max-25612gb-zaa-not-active"
    assert r0["image"].endswith("x.png")
    assert r0["brand"] == "apple"
    assert r0["extra"]["guarantee"] == "18ماه گارانتی شرکتی"
    # colours of one product stay separate offers
    assert {r["id"] for r in rows} == {"11168", "11169", "11170"}


def test_kasrapars_api_sale_price_beats_price_main_and_stock_is_mapped():
    src = build_source(_api_cfg(), base_dir=str(ROOT))
    rows, _ = src._api_rows(_api_payload())
    off = next(r for r in rows if r["id"] == "11170")
    assert off["price"] == 3510000000                            # price_off wins
    assert off["extra"]["old_price"] == 3600000000               # price_main kept as metadata
    assert off["stock"] == "ناموجود"
    assert off["image"] == ""


def test_kasrapars_api_payload_shape_mismatch_falls_back_to_generic_json():
    src = build_source(_api_cfg(), base_dir=str(ROOT))
    rows, nxt = src._api_rows({"products": [{"name": "x", "price": 1}]})
    assert rows == [] and nxt == ""


def test_kasrapars_api_source_fetch_uses_normal_offer_contract(monkeypatch):
    cfg = _api_cfg()
    src = build_source(cfg, base_dir=str(ROOT))
    body = json.dumps(_api_payload(), ensure_ascii=False)
    monkeypatch.setattr(src, "read", lambda u: body)
    offers = src.fetch([])
    assert len(offers) == 3
    assert all(o.currency_unit_raw == "rial" for o in offers)    # unit stays declarative
    assert {o.stock for o in offers} == {"IN_STOCK", "OUT_OF_STOCK"}
    assert all(o.price_raw == float(o.price_raw) and o.price_raw > 0 for o in offers)


def test_kasrapars_api_pagination_follows_next_links(monkeypatch):
    payload = _api_payload()
    page2 = json.loads(json.dumps(payload, ensure_ascii=False))
    page2["items"]["items"][0]["varieties"] = [dict(page2["items"]["items"][0]["varieties"][0], id=99999)]
    page2["items"]["items"] = page2["items"]["items"][:1]
    page2["items"]["_links"] = {"self": {"href": "...page=2"}}   # no next on the last page
    pages = {
        "https://api.kasrapars.ir/api/web/v10/product/index-brand?page=1": json.dumps(payload, ensure_ascii=False),
        "https://api.kasrapars.ir/api/web/v10/product/index-brand?page=2": json.dumps(page2, ensure_ascii=False),
    }
    src = build_source(_api_cfg(follow_next=True), base_dir=str(ROOT))
    monkeypatch.setattr(src, "read", lambda u: pages[u])
    rows = src.records([])
    assert src.raw_count == 4                                    # 3 + 1, deduped across pages
    assert {r["id"] for r in rows} == {"11168", "11169", "11170", "99999"}


def test_kasrapars_api_nonempty_catalog_note_and_titles(monkeypatch):
    src = build_source(_api_cfg(), base_dir=str(ROOT))
    monkeypatch.setattr(src, "read", lambda u: json.dumps(_api_payload(), ensure_ascii=False))
    src.records([])
    assert src.raw_count == 3
    assert any("iPhone 17 Pro Max" in t for t in src.catalog_titles)
    assert "pages=1" in src.note


def test_kasrapars_api_offers_join_other_shops_in_full_run(tmp_path):
    srcs = [
        {"name": "kasrapars", "type": "kasrapars", "currency_unit": "rial", "priority": 50,
         "min_expected_products": 1, "base_url": "https://plus.kasrapars.ir/", "follow_next": False,
         "path": "fixtures/kasrapars_api.json"},
        {"name": "eways", "type": "csv", "currency_unit": "toman", "priority": 10, "min_expected_products": 1,
         "path": "fixtures/e.csv",
         "columns": {"id": "sku", "title": "title", "price": "price", "stock": "stock", "url": "link"}},
    ]
    cfg, base = make_project(tmp_path, sources=srcs,
                             watchlist=[{"id": "a56", "brand": "samsung", "model": "Galaxy A56", "storage": 256, "ram": 8}])
    (Path(base) / "fixtures/e.csv").write_text(
        "sku,title,price,stock,link\ne1,Samsung Galaxy A56 5G 8GB 256GB Black,106000000,موجود,https://e/1\n",
        encoding="utf-8")
    payload = {"items": {"items": [{
        "id": 500, "brand_id": 1, "slug": "samsung-galaxy-a56-5g-8256-black",
        "product_name_en": "Samsung Galaxy A56 5G 8GB 256GB Black",
        "src": "",
        "varieties": [{"id": 600, "price_main": 1073900000, "price_off": 1073900000,
                       "color": {"color_name": "مشکی (Black)"},
                       "status": {"title": "موجود", "can_buy": True}}],
    }], "_links": {}, "_meta": {"totalCount": 1, "pageCount": 1, "currentPage": 1, "perPage": 20}},
        "filters": {"brands": [{"id": 1, "brand_name_en": "samsung", "brand_name": "سامسونگ"}]}}
    (Path(base) / "fixtures/kasrapars_api.json").write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    res = run(cfg, base_dir=base)
    assert res.exit_code == 0
    p = res.doc["products"][0]
    black = next(v for v in p["variants"] if v["variant"] == "black")
    assert {o["source"] for o in black["offers"]} == {"kasrapars", "eways"}
    # kasrapars: 1,073,900,000 rial = 107,390,000 toman  ->  eways at 106,000,000 toman is cheaper
    assert black["winner"]["source"] == "eways"
    kp = next(o for o in black["offers"] if o["source"] == "kasrapars")
    assert kp["price_toman"] == 107390000
