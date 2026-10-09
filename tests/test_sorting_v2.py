"""V2 §9: most-expensive-first ordering of products (and colours) — identical across all outputs."""
import json
from conftest_helpers import make_project
from pricecompare import report
from pricecompare.pricing import reference_price
from pricecompare.runner import run


def _refs(doc):
    return [reference_price(p) for p in doc["products"] if reference_price(p) is not None]


def test_products_sorted_descending_by_reference_price(tmp_path):
    cfg, base = make_project(tmp_path)
    res = run(cfg, base_dir=base)
    refs = _refs(res.doc)
    assert refs == sorted(refs, reverse=True)
    assert refs[0] == 89_100_000 and refs[-1] == 9_750_000
    # products WITHOUT a valid price form the trailing section
    tail = [p for p in res.doc["products"] if reference_price(p) is None]
    assert tail and all(p["status"] in ("not_found", "no_valid_price") for p in tail)
    assert res.doc["products"][-len(tail):] == tail if tail else True


def test_colours_sorted_descending_within_product(tmp_path):
    cfg, base = make_project(tmp_path)
    res = run(cfg, base_dir=base)
    p = next(p for p in res.doc["products"] if p["id"] == "iphone17-256")
    lows = []
    for v in p["variants"]:
        vals = [o["price_toman"] for o in v["offers"] if o["valid"]]
        lows.append(min(vals) if vals else None)
    priced = [x for x in lows if x is not None]
    assert priced == sorted(priced, reverse=True)


def test_same_order_in_json_csv_markdown_and_telegram(tmp_path):
    cfg, base = make_project(tmp_path)
    res = run(cfg, base_dir=base)
    doc = res.doc
    titled = [p.get("title") or p.get("label") for p in doc["products"]]
    # CSV: rows grouped by product in the same order (products with at least one variant row)
    import csv, io
    rows = list(csv.DictReader(io.StringIO((base_dir_csv(tmp_path) / "report.csv").read_text(encoding="utf-8-sig"))))
    csv_order = []
    for r in rows:
        t = r["canonical_title"]
        if not csv_order or csv_order[-1] != t:
            csv_order.append(t)
    has_variants = {p.get("title") or p.get("label") for p in doc["products"] if p["variants"]}
    assert csv_order == [t for t in titled if t in has_variants]
    # markdown: "## " headings follow the same order (all products, priced or not)
    md = (base_dir_csv(tmp_path) / "report.md").read_text(encoding="utf-8")
    md_order = [t for t in titled if f"## {t}" in md]
    assert md_order == titled
    # telegram: product blocks appear in the same order
    msgs = report.build_telegram_messages(doc, "none")
    text = "\n".join(msgs)
    pos = []
    for t in titled:
        i = text.find(f"📱 {t}")
        if i >= 0:
            pos.append((i, t))
    tg_order = [t for _, t in sorted(pos)]
    expected = [t for t in titled if f"📱 {t}" in text]
    assert tg_order == expected
    # JSON output file keeps the same order as the in-memory doc
    on_disk = json.loads((base_dir_csv(tmp_path) / "output.json").read_text(encoding="utf-8"))
    assert [p["id"] for p in on_disk["products"]] == [p["id"] for p in doc["products"]]


def base_dir_csv(tmp_path):
    return tmp_path / "out"


def test_tie_broken_stably_by_title(tmp_path):
    from pricecompare.pricing import sort_products
    a = {"id": "a", "title": "Alpha 128GB", "label": "Alpha 128GB", "model": "Alpha",
         "variants": [{"winner": {"price_toman": 100}, "offers": [], "variant": "black"}]}
    b = {"id": "b", "title": "Beta 128GB", "label": "Beta 128GB", "model": "Beta",
         "variants": [{"winner": {"price_toman": 100}, "offers": [], "variant": "black"}]}
    c = {"id": "c", "title": "Gamma 256GB", "label": "Gamma 256GB", "model": "Gamma",
         "variants": [{"winner": {"price_toman": 900}, "offers": [], "variant": "black"}]}
    out = sort_products([a, b, c])
    assert [p["id"] for p in out] == ["c", "a", "b"]          # 900 first, then stable title order
    assert sort_products([b, a, c]) == out                    # input order never matters


def test_reference_price_is_the_lowest_valid_colour_price(tmp_path):
    cfg, base = make_project(tmp_path)
    res = run(cfg, base_dir=base)
    p = next(p for p in res.doc["products"] if p["id"] == "iphone17-256")
    expected = min(min(o["price_toman"] for o in v["offers"] if o["valid"])
                   for v in p["variants"] if any(o["valid"] for o in v["offers"]))
    assert reference_price(p) == expected == 64_100_000
