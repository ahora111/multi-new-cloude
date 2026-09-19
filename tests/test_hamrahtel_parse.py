"""Regression for the real-run bug: prices of the previous card were attached to the next card's title."""
import importlib
from types import SimpleNamespace


def _h():
    try:
        return importlib.import_module("pricecompare.sources.vendor.hamrahtel_scraper")
    except ImportError:
        return None


def _parse(lines):
    h = _h()
    return [(p.brand, p.model, p.price, p.color) for p in h.parse_body_lines([h.clean_text(x) for x in lines])]


def test_each_price_gets_its_own_title_and_colour():
    if not _h():
        return
    got = _parse(["جستجو", "Galaxy A17 128GB RAM 4GB Vietnam", "مشکی", "47,299,000 تومان", "خاکستری", "47,199,000 تومان",
                  "Galaxy A17 128GB RAM 6GB Vietnam", "مشکی", "56,499,000 تومان", "سبز", "100,799,000 تومان",
                  "iPhone 17 256GB CH/A Non Active", "آبی", "349,000,000 تومان"])
    assert ("Galaxy", "A17 128GB RAM 4GB Vietnam", "47,299,000", "مشکی") in got
    assert ("Galaxy", "A17 128GB RAM 6GB Vietnam", "56,499,000", "مشکی") in got
    assert ("iPhone", "17 256GB CH/A Non Active", "349,000,000", "آبی") in got
    assert not [g for g in got if "4GB" in g[1] and g[2] == "56,499,000"]        # the old bug
    assert len(got) == 5


def test_variant_without_colour_does_not_inherit_previous_colour():
    if not _h():
        return
    got = _parse(["Redmi Note 14 256GB", "مشکی", "13,700,000", "13,900,000"])
    assert ("Redmi", "Note 14 256GB", "13,700,000", "مشکی") in got
    assert ("Redmi", "Note 14 256GB", "13,900,000", "") in got


def test_title_that_mentions_a_colour_is_still_a_title():
    if not _h():
        return
    got = _parse(["Galaxy A17 128GB RAM 4GB مشکی", "47,299,000"])
    assert got == [("Galaxy", "A17 128GB RAM 4GB مشکی", "47,299,000", "")]      # colour stays in the title text


def test_body_fallback_reads_rendered_page_text():
    h = _h()
    if not h:
        return
    body = "منو\nGalaxy A16 128GB RAM 4GB\nمشکی\n43,299,000 تومانءء\n"
    page = SimpleNamespace(locator=lambda sel: SimpleNamespace(inner_text=lambda timeout=0: body))
    assert [(p.model, p.price, p.color) for p in h.extract_body_text_fallback(page)] == [("A16 128GB RAM 4GB", "43,299,000", "مشکی")]


def test_debug_lines_are_numbered_around_first_price():
    if not _h():
        return
    from pricecompare.sources.hamrahtel import debug_lines
    out = debug_lines(["a"] * 30 + ["Galaxy A17", "47,299,000"], n=5, context=2)
    assert out[0] == "  29 | a" and out[1].endswith("Galaxy A17") and out[2].endswith("47,299,000")
