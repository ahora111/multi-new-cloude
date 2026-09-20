"""Parser tests based on a REAL page dump of hamrahtel.com/quick-checkout (rendered text lines, digits Persian-style)."""
import importlib
from types import SimpleNamespace

REAL = """برند
رنگ
سامسونگ
Galaxy A16 128GB RAM 4GB Vietnam
مشکی
43٬299٬000
افزودن
خاکستری
43٬199٬000
افزودن
Galaxy A36 5G 256GB RAM 8GB Vietnam
لیمویی
86٬599٬000
افزودن
سفید
86٬990٬000
افزودن
یاسی
86٬599٬000
افزودن
Galaxy A17 128GB RAM 4GB Vietnam
مشکی
47٬299٬000
افزودن
آبی روشن
47٬199٬000
افزودن
خاکستری
47٬199٬000
افزودن
Galaxy A17 128GB RAM 6GB Vietnam
مشکی
56٬499٬000
افزودن
شیائومی - xiaomi
Redmi A3 128GB RAM 4GB
مشکی
34٬390٬000
35٬390٬000
%3
افزودن
ابی
34٬090٬000
35٬090٬000
%3
افزودن
اپل Apple
iPhone 16 Pro Max 1TB ZA/A Non Active
Black Titanium
478٬890٬000
افزودن
iPhone 16 128GB CH/A Non Active
Black
306٬990٬000
افزودن
نوکیا
NOKIA 106 FA مونتاژ ایران
مشکی
2٬999٬000
افزودن""".splitlines()


def _h():
    try:
        return importlib.import_module("pricecompare.sources.vendor.hamrahtel_scraper")
    except ImportError:
        return None


def _parse(lines):
    h = _h()
    return [(p.brand, p.model, p.price, p.color, p.stock) for p in h.parse_body_lines([h.clean_text(x) for x in lines])]


def test_real_layout_every_row_gets_its_own_title_and_colour():
    if not _h():
        return
    got = _parse(REAL)
    a17 = [g for g in got if g[1] == "A17 128GB RAM 4GB Vietnam"]
    assert [(g[2], g[3]) for g in a17] == [("47٬299٬000", "مشکی"), ("47٬199٬000", "آبی روشن"), ("47٬199٬000", "خاکستری")]
    six = [g for g in got if g[1] == "A17 128GB RAM 6GB Vietnam"]
    assert [(g[2], g[3]) for g in six] == [("56٬499٬000", "مشکی")]                # not attached to the 4GB title
    assert len(got) == 14                                                            # one product per price row


def test_button_text_headers_and_unknown_colours_are_never_titles():
    if not _h():
        return
    got = _parse(REAL)
    models = {g[1] for g in got}
    assert "افزودن" not in models and "لیمویی" not in models and "یاسی" not in models
    assert all(any(c.isdigit() for c in g[1]) for g in got)                          # every title has digits
    a36 = [g for g in got if g[1].startswith("A36")]
    assert [g[3] for g in a36] == ["لیمویی", "سفید", "یاسی"]                          # raw colour labels survive


def test_discount_row_uses_the_first_price_only():
    if not _h():
        return
    got = [g for g in _parse(REAL) if g[1].startswith("Redmi") or g[0] == "Redmi"]
    assert [(g[2], g[3]) for g in got] == [("34٬390٬000", "مشکی"), ("34٬090٬000", "ابی")]


def test_iphone_titles_with_region_codes_and_english_colours():
    if not _h():
        return
    got = {g[1]: g for g in _parse(REAL) if g[0] == "iPhone"}
    assert got["16 Pro Max 1TB ZA/A Non Active"][3] == "Black Titanium"
    assert got["16 128GB CH/A Non Active"][2:4] == ("306٬990٬000", "Black")


def test_header_lines_before_first_title_are_ignored_and_out_of_stock_is_detected():
    if not _h():
        return
    got = _parse(["برند", "رنگ", "سامسونگ", "47٬299٬000", "Galaxy A17 128GB RAM 4GB", "مشکی", "47٬299٬000", "ناموجود", "سفید", "47٬199٬000", "افزودن"])
    assert got == [("Galaxy", "A17 128GB RAM 4GB", "47٬299٬000", "مشکی", "out_of_stock"),
                   ("Galaxy", "A17 128GB RAM 4GB", "47٬199٬000", "سفید", "in_stock")]


def test_body_fallback_reads_rendered_page_text():
    h = _h()
    if not h:
        return
    body = "\n".join(REAL)
    page = SimpleNamespace(locator=lambda sel: SimpleNamespace(inner_text=lambda timeout=0: body))
    assert len(h.extract_body_text_fallback(page)) == len(_parse(REAL))


def test_debug_lines_are_numbered_around_first_price():
    if not _h():
        return
    from pricecompare.sources.hamrahtel import debug_lines
    out = debug_lines(["a"] * 30 + ["Galaxy A17", "47,299,000"], n=5, context=2)
    assert out[0] == "  29 | a" and out[1].endswith("Galaxy A17") and out[2].endswith("47,299,000")


def test_real_layout_end_to_end_prices_only_the_right_rows(tmp_path, monkeypatch):
    sc = _h()
    if not sc:
        return
    from conftest_helpers import make_project
    from pricecompare.runner import run
    products = sc.parse_body_lines([sc.clean_text(x) for x in REAL])
    monkeypatch.setattr(sc, "fetch_all_products", lambda o: (products, True))
    wl = [{"id": "a17", "brand": "samsung", "model": "Galaxy A17 4G", "storage": 128, "ram": 4},
          {"id": "iphone16", "brand": "apple", "model": "iPhone 16", "storage": 128, "region": "CH/A", "condition": "non_active"}]
    cfg, base = make_project(tmp_path, sources=[{"name": "hamrahtel", "type": "hamrahtel", "currency_unit": "toman"}], watchlist=wl)
    res = run(cfg, base_dir=base)
    by = {p["id"]: {v["variant"]: v["winner"]["price_toman"] for v in p["variants"] if v["winner"]} for p in res.doc["products"]}
    assert by["a17"] == {"black": 47_299_000, "light blue": 47_199_000, "gray": 47_199_000}
    assert by["iphone16"] == {"black": 306_990_000}                                # Pro Max 1TB is a different product
