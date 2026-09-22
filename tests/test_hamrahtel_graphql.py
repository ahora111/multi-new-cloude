"""Hamrahtel serves a Saleor-style GraphQL API (seen in the real debug dump): structured prices, colours, real stock."""
import importlib
import json
import sys
from conftest_helpers import make_project
from pricecompare.config import SourceConfig
from pricecompare.runner import run
from pricecompare.sources import build_source


def _mods():
    try:
        sc = importlib.import_module("pricecompare.sources.vendor.hamrahtel_scraper")
        return sc, importlib.import_module("pricecompare.sources.hamrahtel")
    except ImportError:
        return None, None


def variant(vid, color, amount, qty, undiscounted=None):
    return {"id": vid, "name": color, "marketplacePrice": None, "quantityAvailable": qty,
            "pricing": {"price": {"gross": {"amount": amount}}, "priceUndiscounted": {"gross": {"amount": undiscounted or amount}}, "discount": None},
            "attributes": [{"attribute": {"name": "رنگ", "slug": "color"}, "values": [{"name": " " + color, "value": "#000000"}]}]}


def node(name, slug, variants, available=True):
    return {"id": "P:" + slug, "name": name, "isAvailable": available, "isAvailableForPurchase": available, "slug": slug, "variants": variants}


def payload(*nodes):
    return {"data": {"publicProducts": {"totalCount": len(nodes), "pageInfo": {"hasNextPage": False},
                                        "edges": [{"node": n} for n in nodes]}}}


A17 = node("Galaxy A17 128GB RAM 4GB Vietnam", "galaxy-a17-128-4", [variant("v1", "مشکی", 47299000.0, 4), variant("v2", "خاکستری", 47199000.0, 0)])
IP17 = node("iPhone 17 256GB CH/A Non Active", "iphone-17-256", [variant("v3", "Mist Blue", 348990000.0, 12)])
GONE = node("Galaxy A07 64GB RAM 4GB", "a07", [variant("v4", "سبز", 33099000.0, 5)], available=False)
LINES = ["Galaxy A17 128GB RAM 4GB Vietnam", "مشکی", "47٬299٬000", "افزودن", "iPhone 17 256GB CH/A Non Active", "Mist Blue", "348٬990٬000", "افزودن"]


def test_nodes_are_found_anywhere_and_variants_become_records():
    sc, hm = _mods()
    if not sc:
        return
    nodes = hm.nodes_from_json({"data": {"x": [payload(A17)["data"]["publicProducts"]]}, "extensions": {}})
    assert [n["name"] for n in nodes] == ["Galaxy A17 128GB RAM 4GB Vietnam"]
    recs = hm.records_from_nodes(hm.nodes_from_json(payload(A17, IP17, GONE)), link="https://h/x")
    by = {r["id"]: r for r in recs}
    assert by["v1"]["price"] == 47299000.0 and by["v1"]["stock"] == "in_stock" and by["v1"]["color"] == "مشکی"
    assert by["v2"]["stock"] == "out_of_stock"                       # quantityAvailable == 0
    assert by["v4"]["stock"] == "out_of_stock"                       # product not available for purchase
    assert by["v3"]["url"] == "https://h/x"


def test_graphql_structured_color_attribute_preserves_sage_green():
    sc, hm = _mods()
    if not sc:
        return
    sage = node("iPhone 17 256GB CH/A Non Active", "iphone-17-256",
                [variant("sage-1", "variant-internal-name", 345990000.0, 7)])
    sage["variants"][0]["attributes"] = [
        {"attribute": {"name": "رنگ", "slug": "color"},
         "values": [{"name": " Sage Green", "value": "#9CAF88"}]}
    ]
    recs = hm.records_from_nodes([sage], link="L")
    assert recs[0]["color"] == "Sage Green"


def test_product_url_template_and_duplicate_variants():
    sc, hm = _mods()
    if not sc:
        return
    recs = hm.records_from_nodes([A17, A17], link="L", url_template="https://hamrahtel.com/product/{slug}")
    assert len(recs) == 2 and recs[0]["url"] == "https://hamrahtel.com/product/galaxy-a17-128-4"


def _plugin(monkeypatch, nodes, lines, **opts):
    sc, hm = _mods()
    monkeypatch.setattr(hm, "browse_hamrahtel", lambda *a, **k: (nodes, lines))
    return build_source(SourceConfig("hamrahtel", "hamrahtel", "toman", options=opts))


def test_auto_prefers_graphql_and_reports_the_strategy(monkeypatch):
    sc, hm = _mods()
    if not sc:
        return
    src = _plugin(monkeypatch, hm.nodes_from_json(payload(A17, IP17)), LINES)
    offers = {o.source_offer_id: o for o in src.fetch([])}
    assert set(offers) == {"v1", "v2", "v3"} and offers["v2"].stock == "OUT_OF_STOCK"
    assert src.note.startswith("strategy=graphql (graphql=3, text=2)") and src.raw_count == 3


def test_auto_falls_back_to_page_text_when_graphql_is_missing_or_incomplete(monkeypatch):
    sc, hm = _mods()
    if not sc:
        return
    src = _plugin(monkeypatch, [], LINES)
    assert len(src.fetch([])) == 2 and src.note.startswith("strategy=text")
    many_lines = LINES * 5                                              # text sees far more than the API returned
    src2 = _plugin(monkeypatch, hm.nodes_from_json(payload(IP17)), many_lines)
    src2.fetch([])
    assert src2.note.startswith("strategy=text") and "incomplete" in src2.note


def test_explicit_strategies_and_errors(monkeypatch):
    sc, hm = _mods()
    if not sc:
        return
    n = hm.nodes_from_json(payload(A17))
    assert len(_plugin(monkeypatch, n, LINES, strategy="text").fetch([])) == 2
    assert len(_plugin(monkeypatch, n, LINES, strategy="graphql").fetch([])) == 2
    for bad, exc, text in (({"strategy": "graphql"}, RuntimeError, "zero products"), ({"strategy": "nope"}, ValueError, "strategy must be")):
        try:
            _plugin(monkeypatch, [], [], **bad).fetch([])
        except exc as e:
            assert text in str(e)
        else:
            raise AssertionError("expected an error")


def test_end_to_end_graphql_prices_and_stock(tmp_path, monkeypatch):
    sc, hm = _mods()
    if not sc:
        return
    monkeypatch.setattr(hm, "browse_hamrahtel", lambda *a, **k: (hm.nodes_from_json(payload(A17, IP17)), LINES))
    wl = [{"id": "a17", "brand": "samsung", "model": "Galaxy A17 4G", "storage": 128, "ram": 4},
          {"id": "ip17", "brand": "apple", "model": "iPhone 17", "storage": 256, "region": "CH/A", "condition": "non_active"}]
    cfg, base = make_project(tmp_path, sources=[{"name": "hamrahtel", "type": "hamrahtel", "currency_unit": "toman"}], watchlist=wl)
    res = run(cfg, base_dir=base)
    by = {p["id"]: {v["variant"]: v["winner"]["price_toman"] for v in p["variants"] if v["winner"]} for p in res.doc["products"]}
    assert by["a17"] == {"black": 47_299_000}                          # gray is out of stock (quantity 0): no winner
    assert by["ip17"] == {"blue": 348_990_000}
    assert res.doc["sources"][0]["note"].startswith("strategy=graphql")


def test_auto_supplements_graphql_when_rendered_page_has_sage_green_variant(monkeypatch):
    sc, hm = _mods()
    if not sc:
        return
    nodes = []
    lines = []
    for i in range(10):
        title = f"iPhone 17 {256 + i}GB CH/A Non Active"
        color = "Blue"
        nodes.append(node(title, f"iphone-17-{256+i}", [variant(f"v-{i}", color, 345500000.0 + i, 8)]))
        lines += [title, color, f"{345500000 + i:,}", "افزودن"]
    # The rendered page contains one extra variant which GraphQL omitted.
    lines += ["iPhone 17 256GB CH/A Non Active", "Sage Green", "345٬990٬000", "افزودن"]
    src = _plugin(monkeypatch, hm.nodes_from_json(payload(*nodes)), lines)
    offers = src.fetch([])
    assert len(offers) == 11
    by_color = {o.raw_color: o.price_raw for o in offers if o.raw_title.startswith("iPhone 17 256GB")}
    assert by_color["Blue"] == 345500000.0
    assert by_color["Sage Green"] == 345990000.0
    assert src.note.startswith("strategy=graphql+text-supplement")
