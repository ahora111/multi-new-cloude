"""Tests for the Digikala B2B source (b2b.digikala.com JSON API).

Fixtures are REAL API payloads (captured 2026-10-03):
  digikala_b2b_listing.json      GET /api/v1/products?category_id=3&page=1&sort=price-desc
  digikala_b2b_pdp_31765.json    GET /api/v1/products/pdp/31765  (1 colour, in stock)
  digikala_b2b_pdp_14428.json    GET /api/v1/products/pdp/14428  (3 colours, 2 warranties)

Domain facts pinned here:
  * listing rows have no stock flag; price == 0 + no colours ⇔ sold out
  * meta.links.next is http:// and must be upgraded to https://
  * PDP variants carry per-colour price, warranty and remaining_stock (null = no limit)
"""
import json
from pathlib import Path

from pricecompare.config import SourceConfig
from pricecompare.models import Offer
from pricecompare.extract import Extractor
from pricecompare.discovery import discover, display_name
from pricecompare.sources import build_source
from pricecompare.sources.digikala_b2b import parse_listing_payload, parse_pdp_payload

ROOT = Path(__file__).resolve().parents[1]
LISTING = json.loads((ROOT / "fixtures" / "digikala_b2b_listing.json").read_text(encoding="utf-8"))
PDP_SINGLE = json.loads((ROOT / "fixtures" / "digikala_b2b_pdp_31765.json").read_text(encoding="utf-8"))
PDP_MULTI = json.loads((ROOT / "fixtures" / "digikala_b2b_pdp_14428.json").read_text(encoding="utf-8"))

BASE_URL = "https://b2b.digikala.com/"


def _cfg(**opts):
    base = {"path": "fixtures/digikala_b2b_listing.json", "base_url": BASE_URL, "details": "none"}
    base.update(opts)
    return SourceConfig("digikala_b2b", "digikala_b2b", "rial", min_expected_products=1, options=base)


# ---------- listing payload ----------

def test_listing_parses_title_price_image_and_spa_product_url():
    rows, nxt = parse_listing_payload(LISTING, BASE_URL)
    r = next(x for x in rows if x["id"] == "31765")
    assert r["title"].startswith("گوشی موبایل اپل مدل iPhone 17 Pro Max ZAA")
    assert r["price"] == 5_199_990_000                     # RIAL
    assert r["stock"] == "in_stock"
    assert r["url"] == "https://b2b.digikala.com/products/product/31765"
    assert r["image"].startswith("https://dkstatics-public.digikala.com/")
    assert r["color"] == "آبی تیره"                        # single colour -> listing price belongs to it
    assert r["extra"]["short_title"].startswith("Apple iPhone 17 Pro Max ZAA")


def test_listing_sold_out_row_has_price_zero_and_no_colours():
    rows, _ = parse_listing_payload(LISTING, BASE_URL)
    r = next(x for x in rows if x["id"] == "69001")        # Samsung Galaxy A27, really sold out
    assert r["price"] is None and r["stock"] == "out_of_stock"
    assert r["color"] == "" and r["extra"]["listing_colors"] == []


def test_listing_multi_colour_row_keeps_colour_empty_for_pdp_refinement():
    rows, _ = parse_listing_payload(LISTING, BASE_URL)
    r = next(x for x in rows if x["id"] == "14428")        # Galaxy A36 with 3 colours
    assert r["color"] == "" and len(r["extra"]["listing_colors"]) == 3
    assert r["price"] == 999_990_000                       # min variant price (lemon yellow)


def test_listing_next_link_is_upgraded_to_https():
    _, nxt = parse_listing_payload(LISTING, BASE_URL)
    assert nxt == "https://b2b.digikala.com/api/v1/products?category_id=3&page=2&sort=price-desc"


def test_listing_last_page_has_no_next():
    payload = json.loads(json.dumps(LISTING, ensure_ascii=False))
    payload["data"] = payload["data"][:1]
    payload["meta"]["last_page"] = 1
    payload["meta"]["current_page"] = 1
    payload["links"]["next"] = None
    rows, nxt = parse_listing_payload(payload, BASE_URL)
    assert rows and nxt == ""


# ---------- PDP payload ----------

def test_pdp_splits_variants_with_exact_colour_price_and_warranty():
    recs = parse_pdp_payload(PDP_MULTI, BASE_URL)
    assert [r["id"] for r in recs] == ["14428:35168", "14428:36034", "14428:68217"]
    black = recs[0]
    assert black["color"] == "مشکی" and black["price"] == 1_010_000_000
    assert black["stock"] == "in_stock"                    # remaining_stock == 1
    assert black["extra"]["warranty"] == "گارانتی 18 ماهه -شرکتی"
    assert black["url"] == "https://b2b.digikala.com/products/product/14428"
    yellow = recs[2]
    assert yellow["color"] == "زرد لیمویی" and yellow["price"] == 999_990_000
    assert yellow["stock"] == "in_stock"                   # remaining_stock null = no explicit limit


def test_pdp_single_variant_matches_listing_price():
    recs = parse_pdp_payload(PDP_SINGLE, BASE_URL)
    assert len(recs) == 1
    r = recs[0]
    assert r["id"] == "31765:34187" and r["price"] == 5_199_990_000
    assert r["color"] == "آبی تیره" and r["stock"] == "in_stock"


def test_pdp_sold_out_product_emits_single_oos_record():
    payload = {"data": {"id": 999, "name": "گوشی موبایل X", "price": 0, "in_stock": False, "variants": []}}
    recs = parse_pdp_payload(payload, BASE_URL)
    assert len(recs) == 1
    assert recs[0]["stock"] == "out_of_stock" and recs[0]["price"] is None


def test_pdp_remaining_stock_zero_is_out_of_stock():
    payload = json.loads(json.dumps(PDP_SINGLE, ensure_ascii=False))
    payload["data"]["variants"][0]["remaining_stock"] = 0
    recs = parse_pdp_payload(payload, BASE_URL)
    assert recs[0]["stock"] == "out_of_stock" and recs[0]["price"] == 5_199_990_000


# ---------- source contract ----------

def test_source_fetch_rial_offer_contract_with_pdp_refinement(monkeypatch):
    """With details=all every in-stock listing row is refined into per-variant offers."""
    bodies = {
        "fixtures/digikala_b2b_listing.json": json.dumps(LISTING, ensure_ascii=False),
        f"{BASE_URL}api/v1/products/pdp/14428": json.dumps(PDP_MULTI, ensure_ascii=False),
        f"{BASE_URL}api/v1/products/pdp/31765": json.dumps(PDP_SINGLE, ensure_ascii=False),
        f"{BASE_URL}api/v1/products/pdp/44258": json.dumps(PDP_MULTI, ensure_ascii=False),
        f"{BASE_URL}api/v1/products/pdp/207697": json.dumps(PDP_SINGLE, ensure_ascii=False),
        f"{BASE_URL}api/v1/products/pdp/14430": json.dumps(PDP_MULTI, ensure_ascii=False),
    }
    src = build_source(_cfg(details="all"), base_dir=str(ROOT))
    monkeypatch.setattr(src, "read", lambda u: bodies[u])
    offers = src.fetch([])
    assert all(o.currency_unit_raw == "rial" for o in offers)   # unit stays declarative
    refined = next(o for o in offers if o.source_offer_id == "14428:35168")
    assert refined.price_raw == 1_010_000_000 and refined.raw_color == "مشکی"
    assert refined.stock == "IN_STOCK"
    assert refined.extra["warranty"] == "گارانتی 18 ماهه -شرکتی"


def test_source_details_none_keeps_listing_rows_without_pdp_calls(monkeypatch):
    src = build_source(_cfg(details="none"), base_dir=str(ROOT))
    calls = []

    def fake_read(u):
        calls.append(u)
        return json.dumps(LISTING, ensure_ascii=False)
    monkeypatch.setattr(src, "read", fake_read)
    offers = src.fetch([])
    assert len(calls) == 1                                   # only the listing page
    assert {o.source_offer_id for o in offers} <= {"31765", "44258", "14428", "207697", "14430"}
    assert next(o for o in offers if o.source_offer_id == "14428").raw_color == ""


def test_source_candidates_fetch_pdp_only_for_matching_watchlist(monkeypatch):
    src = build_source(_cfg(details="candidates"), base_dir=str(ROOT))
    pdp_calls = []

    def fake_read(u):
        if "pdp" in u:
            pdp_calls.append(u)
            assert "14428" in u or "14430" in u
            return json.dumps(PDP_MULTI, ensure_ascii=False)
        return json.dumps(LISTING, ensure_ascii=False)
    monkeypatch.setattr(src, "read", fake_read)
    watch = [type("W", (), {"id": "a36", "brand": "samsung", "model": "Galaxy A36",
                            "storage_gb": 256, "ram_gb": 8})()]
    offers = src.fetch(watch)
    assert pdp_calls                                         # Samsung A36 refined...
    assert all(not o.source_offer_id.startswith("31765:") for o in offers)  # ...iPhone was not


def test_source_pdp_failure_falls_back_to_listing_row(monkeypatch):
    def fake_read(u):
        if "pdp" in u:
            raise IOError("boom")
        return json.dumps(LISTING, ensure_ascii=False)
    src = build_source(_cfg(details="all"), base_dir=str(ROOT))
    monkeypatch.setattr(src, "read", fake_read)
    offers = src.fetch([])
    assert next(o for o in offers if o.source_offer_id == "31765").price_raw == 5_199_990_000


def test_source_out_of_stock_filtering(monkeypatch):
    src = build_source(_cfg(details="none"), base_dir=str(ROOT))   # include_out_of_stock defaults to False
    monkeypatch.setattr(src, "read", lambda u: json.dumps(LISTING, ensure_ascii=False))
    offers = src.fetch([])
    assert all(o.stock == "IN_STOCK" for o in offers)        # 69001 dropped by default

    src2 = build_source(_cfg(details="none", include_out_of_stock=True), base_dir=str(ROOT))
    monkeypatch.setattr(src2, "read", lambda u: json.dumps(LISTING, ensure_ascii=False))
    offers2 = src2.fetch([])
    oos = next(o for o in offers2 if o.source_offer_id == "69001")
    assert oos.stock == "OUT_OF_STOCK" and oos.price_raw is None


def test_source_pagination_follows_https_upgraded_next(monkeypatch):
    page2 = json.loads(json.dumps(LISTING, ensure_ascii=False))
    page2["data"] = [dict(page2["data"][0], id=777777)]
    page2["meta"] = {"current_page": 2, "last_page": 2}
    page2["links"] = {"next": None}
    pages = {
        "https://b2b.digikala.com/api/v1/products?category_id=3&page=1&sort=price-desc":
            json.dumps(LISTING, ensure_ascii=False),
        "https://b2b.digikala.com/api/v1/products?category_id=3&page=2&sort=price-desc":
            json.dumps(page2, ensure_ascii=False),
    }
    src = build_source(SourceConfig(
        "digikala_b2b", "digikala_b2b", "rial", min_expected_products=1,
        options={"url": "https://b2b.digikala.com/api/v1/products?category_id=3&page=1&sort=price-desc",
                 "base_url": BASE_URL, "details": "none"}), base_dir=str(ROOT))
    monkeypatch.setattr(src, "read", lambda u: pages[u])
    rows = src.records([])
    assert src.raw_count == 7                                # 6 + 1, all kept
    assert "777777" in {r["id"] for r in rows}
    assert "pages=2" in src.note


def test_digikala_title_clusters_with_all_other_sources():
    """The exact digikala Persian title must join the OTHER FOUR sources' iPhone 17 cluster
    (regression guard for the 2026-09-30 split report, now with a fifth shop)."""
    from pricecompare.runner import enrich
    ex = Extractor()
    settings = type("S", (), {"match_auto_threshold": 95, "match_review_threshold": 85})()
    cfg = type("C", (), {"enabled": True, "brands": [], "exclude_regex": "", "min_sources": 1})()

    def offer(source, oid, title, price, color="", unit="toman"):
        o = Offer(source=source, source_offer_id=oid, raw_title=title, price_raw=price,
                  currency_unit_raw=unit, stock="IN_STOCK", raw_color=color)
        return enrich(o, ex)

    offers = [
        offer("kasrapars", "k1", "iPhone 17 256 8GB CH/A Non Active", 362_000_000, "black"),
        offer("hamrahtel", "h1", "iPhone 17 256GB CH/A Non Active", 358_990_000, "black"),
        offer("eways", "e1", "iPhone 17 256GB CH/A Non Active", 359_000_000, "black"),
        offer("farnaa", "f1", "گوشی موبایل اپل مدل iPhone 17 CH دو سیم کارت ظرفیت 256 گیگابایت و رم 8 گیگابایت نات اکتیو",
              355_999_000, "black"),
        # the exact digikala_b2b listing title + its real price in RIAL (pipeline divides by 10)
        offer("digikala_b2b", "d1", "گوشی موبایل اپل مدل iPhone 17 CH دو سیم کارت ظرفیت 256 گیگابایت و رم 8 گیگابایت نات اکتیو ",
              3_559_990_000, "black", unit="rial"),
    ]
    d1 = next(o for o in offers if o.source == "digikala_b2b")
    assert d1.price_toman == 355_999_000                       # rial -> toman in enrich
    assert d1.region == "cha" and d1.condition == "nonactive" and d1.storage_gb == 256 and d1.ram_gb == 8

    items, attrs, members = discover(offers, ex, settings, cfg)
    assert len(items) == 1, f"iPhone 17 split into {len(items)} clusters"
    assert {o.source for o in members[items[0].id]} == {"kasrapars", "hamrahtel", "eways", "farnaa", "digikala_b2b"}
    a = attrs[items[0].id]
    assert display_name(a.core, a.tiers, a.network) == "iPhone 17"


def test_digikala_deep_blue_joins_kasrapars_deep_blue_variant():
    """digikala 'آبی تیره' and kasrapars 'Deep Blue' are the same physical colour
    (iPhone 17 Pro Max ZA/A) — one variant row, not two (the old split-report shape)."""
    from pricecompare.runner import enrich
    ex = Extractor()
    settings = type("S", (), {"match_auto_threshold": 95, "match_review_threshold": 85})()
    cfg = type("C", (), {"enabled": True, "brands": [], "exclude_regex": "", "min_sources": 1})()

    def offer(source, oid, title, price, color, unit="toman"):
        o = Offer(source=source, source_offer_id=oid, raw_title=title, price_raw=price,
                  currency_unit_raw=unit, stock="IN_STOCK", raw_color=color)
        return enrich(o, ex)

    offers = [
        offer("kasrapars", "k3", "iPhone 17 256 Single + Esim Pro Max 12GB ZA/A Non Active", 5_200_000_000,
              "Deep Blue", unit="rial"),
        offer("digikala_b2b", "d3", "گوشی موبایل اپل مدل iPhone 17 Pro Max ZAA تک سیم کارت + eSim ظرفیت 256 گیگابایت و رم 12 گیگابایت - نات اکتیو",
              5_199_990_000, "آبی تیره", unit="rial"),
    ]
    assert all(o.color == "deep_blue" for o in offers)         # canonical colour unification
    items, _, members = discover(offers, ex, settings, cfg)
    assert len(items) == 1, "Pro Max split across colour spellings"
    assert {o.color for o in members[items[0].id]} == {"deep_blue"}
