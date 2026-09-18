from types import SimpleNamespace

from sources.vendor_legacy.hamrahtel_scraper import extract_body_text_fallback


class _Locator:
    def __init__(self, text):
        self._text = text

    def inner_text(self, timeout=10000):
        return self._text


class _Page:
    def __init__(self, text):
        self._text = text

    def locator(self, selector):
        assert selector == "body"
        return _Locator(self._text)


def test_body_fallback_preserves_lines_and_extracts_price():
    page = _Page(
        "Samsung Galaxy A17 128GB RAM 4GB Vietnam\n"
        "مشکی\n"
        "49,799,000 تومان\n"
        "Samsung Galaxy A17 128GB RAM 4GB Vietnam\n"
        "خاکستری\n"
        "51,099,000 تومان\n"
    )
    products = extract_body_text_fallback(page)
    assert len(products) >= 2
    assert any(p.price == "49,799,000" and p.color == "مشکی" for p in products)
    assert any(p.price == "51,099,000" and p.color == "خاکستری" for p in products)
