from core.models import SourceProduct, CanonicalProduct
from core.pricing import choose_lowest

def test_lowest_valid_price():
    a = SourceProduct(source="a", source_product_id="1", brand="x", product_name="x", price=45000000, stock="IN_STOCK")
    b = SourceProduct(source="b", source_product_id="2", brand="x", product_name="x", price=44000000, stock="IN_STOCK")
    c = CanonicalProduct("x", "x", "x", "x", {}, [a,b])
    choose_lowest(c)
    assert c.best_price == 44000000
    assert c.best_source == "b"

def test_out_of_stock_is_ignored():
    a = SourceProduct(source="a", source_product_id="1", brand="x", product_name="x", price=100, stock="OUT_OF_STOCK")
    b = SourceProduct(source="b", source_product_id="2", brand="x", product_name="x", price=200, stock="IN_STOCK")
    c = CanonicalProduct("x", "x", "x", "x", {}, [a,b])
    choose_lowest(c)
    assert c.best_price == 200
