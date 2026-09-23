from pathlib import Path
import yaml

from conftest_helpers import make_project
from pricecompare.extract import Extractor
from pricecompare.models import IN_STOCK, OUT_OF_STOCK
from pricecompare.runner import enrich, run
from pricecompare.sources.exontel import _category_links, parse_product_html
from pricecompare.sources import build_source

ROOT = Path(__file__).resolve().parent.parent
FIXTURE = ROOT / "fixtures" / "exontel_phones.html"


def test_fixture_parses_product_id_url_brand_ram_storage_and_variants():
    rows = parse_product_html(FIXTURE.read_text(encoding="utf-8"), "https://exontel.com/product/exp-303")
    # The fixture contains multiple real product blocks; the source-level helper
    # handles those blocks. Direct parser coverage is tested on one product block.
    from bs4 import BeautifulSoup
    soup = BeautifulSoup(FIXTURE.read_text(encoding="utf-8"), "lxml")
    block = soup.select_one('[data-exontel-product][data-url*="exp-303"]')
    rows = parse_product_html(str(block), block["data-url"])
    assert len(rows) == 3
    assert rows[0]["id"].startswith("exp-303:v")
    assert rows[0]["url"] == "https://exontel.com/product/exp-303"
    assert rows[0]["brand"] == "Samsung"
    assert rows[0]["price"] == "۵۰٬۳۹۰٬۰۰۰ تومان"
    assert rows[0]["stock"] == "in_stock"
    assert rows[1]["stock"] == "out_of_stock"
    assert rows[0]["extra"]["sku"] == "EXP-303"


def test_price_digits_and_canonical_color_are_central():
    ex = Extractor()
    from bs4 import BeautifulSoup
    soup = BeautifulSoup(FIXTURE.read_text(encoding="utf-8"), "lxml")
    block = soup.select_one('[data-exontel-product][data-url*="exp-109"]')
    rows = parse_product_html(str(block), block["data-url"])
    offers = []
    for r in rows:
        from pricecompare.models import Offer
        offers.append(enrich(Offer("exontel", r["id"], r["title"], None, "toman", stock=IN_STOCK,
                                   url=r["url"], raw_color=r["color"], raw_brand=r["brand"],
                                   extra=r["extra"]), ex))
    assert {o.color for o in offers} == {"black", "blue"}
    assert {o.raw_color for o in offers} == {"مشکی (Midnight Black)", "آبی (Star Blue)"}
    assert {o.storage_gb for o in offers} == {128}
    assert {o.ram_gb for o in offers} == {4}


def test_missing_price_brand_and_color_are_not_invented():
    html = """
    <article><h1>Samsung Galaxy A17 128GB RAM 4</h1><div>ناموجود</div><h3>توضیحات محصول</h3></article>
    """
    rows = parse_product_html(html, "https://exontel.com/product/exp-missing")
    assert rows[0]["price"] is None
    assert rows[0]["brand"] == ""
    assert rows[0]["color"] == ""
    assert rows[0]["stock"] == "out_of_stock"


def test_category_links_dedupe_and_keep_real_product_urls():
    html = '<a href="/product/exp-303">A</a><a href="https://exontel.com/product/exp-303">A2</a><a href="/x">x</a>'
    assert _category_links(html, "https://exontel.com/") == ["https://exontel.com/product/exp-303"]


def test_exontel_source_fixture_fetch_and_health(tmp_path):
    cfg, base = make_project(tmp_path)
    sources = yaml.safe_load((Path(cfg) / "sources.yaml").read_text(encoding="utf-8"))["sources"]
    ex = next(s for s in sources if s["name"] == "exontel")
    excfg = type("Cfg", (), {})
    from pricecompare.config import SourceConfig
    sc = SourceConfig(ex["name"], ex["type"], ex["currency_unit"], options={k: v for k, v in ex.items() if k not in {"name","type","currency_unit","priority","min_expected_products","degraded_excluded"}}, min_expected_products=2)
    src = build_source(sc, base_dir=base)
    rows = src.fetch([])
    assert len(rows) == 5
    assert src.raw_count == 5
    assert src.healthcheck().ok


def test_brand_aliases_are_source_independent():
    ex = Extractor()
    pairs = [
        ("کامتل", "comtel"), ("ژیواکو", "zhivaco"), ("ژوبیتر", "jubiter"), ("jphone", "jubiter"),
        ("وکال", "vocal"), ("نمو", "nemo"), ("میدسل", "middcell"), ("جی ال ایکس", "glx"),
        ("تی سی اچ", "tch"), ("جنرال لوکس", "general_luxe"), ("بلووم", "bloom"),
        ("اُرد", "orod"), ("الویا", "elevia"), ("تکنو", "tecno"),
    ]
    assert all(ex.canonical_brand(a) == b for a, b in pairs)


def test_color_aliases_and_separation_are_central():
    ex = Extractor()
    assert {ex.color_of(x, explicit=True) for x in ("Lavender", "Purple", "بنفش")} == {"purple"}
    assert {ex.color_of(x, explicit=True) for x in ("Sage Green", "Green", "سبز")} == {"green"}
    assert {ex.color_of(x, explicit=True) for x in ("Black", "مشکی")} == {"black"}
    assert {ex.color_of(x, explicit=True) for x in ("Gray", "Grey", "خاکستری", "طوسی")} == {"gray"}
    assert ex.color_of("Black", explicit=True) != ex.color_of("Blue", explicit=True)
    assert ex.color_of("Black", explicit=True) != ex.color_of("White", explicit=True)
    assert ex.color_of("Green", explicit=True) != ex.color_of("Purple", explicit=True)


def test_exontel_cross_source_pipeline_one_canonical_product(tmp_path):
    # The ExonTel fixture is combined with three ordinary CSV sources. Matching
    # is performed by the same central discovery/matcher used by every source.
    srcs = [
        {"name":"exontel","type":"exontel","currency_unit":"toman","priority":40,"min_expected_products":2,"path":"fixtures/exontel_phones.html"},
    ]
    for name, title, price in [
        ("eways", "Samsung Galaxy A17 128GB RAM 4 مشکی", 49_800_000),
        ("hamrahtel", "Samsung Galaxy A17 128GB RAM 4 Black", 50_100_000),
        ("farnaa", "Samsung Galaxy A17 128GB RAM 4 Black", 50_000_000),
    ]:
        fn = tmp_path / f"{name}.csv"
        fn.write_text(f"sku,title,price,stock,link\n{name}1,{title},{price},موجود,https://{name}.example/1\n", encoding="utf-8")
        srcs.append({"name":name,"type":"csv","currency_unit":"toman","priority":50,
                     "min_expected_products":1,"path":str(fn),"columns":{"id":"sku","title":"title","price":"price","stock":"stock","url":"link"}})
    cfg, base = make_project(tmp_path / "run", sources=srcs,
                             watchlist=[{"id":"a17","brand":"samsung","model":"Galaxy A17","storage":128,"ram":4}])
    # Copy the fixture into the test project's fixture directory because the
    # source path is relative to the project base.
    (Path(base) / "fixtures" / "exontel_phones.html").write_text(FIXTURE.read_text(encoding="utf-8"), encoding="utf-8")
    res = run(cfg, base_dir=base)
    assert res.exit_code == 0
    p = res.doc["products"][0]
    black = next(v for v in p["variants"] if v["variant"] == "black")
    assert {o["source"] for o in black["offers"]} == {"exontel","eways","hamrahtel","farnaa"}
    assert black["winner"]["source"] == "eways"
