from core.models import SourceProduct, CanonicalProduct
from destinations.telegram import TelegramDestination


def test_telegram_shows_all_compared_products_and_selected_result():
    a = SourceProduct(source="a", source_product_id="1", brand="x", product_name="Product A", price=450, stock="IN_STOCK", url="https://a")
    b = SourceProduct(source="b", source_product_id="2", brand="x", product_name="Product B", price=440, stock="IN_STOCK", url="https://b")
    c = CanonicalProduct("x", "x", "x", "x", {}, [a, b], best_price=440, best_source="b", best_url="https://b", best_stock="IN_STOCK")

    text = TelegramDestination._product_block(c)
    assert "a | 450" in text
    assert "b | 440" in text
    assert "فروشنده انتخاب‌شده: b" in text
    assert "کمترین قیمت معتبر: 440" in text
