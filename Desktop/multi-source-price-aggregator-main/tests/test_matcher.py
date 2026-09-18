from core.models import SourceProduct
from core.matcher import score

def p(name, storage="128GB", color="Black"):
    return SourceProduct(
        source="x", source_product_id="1",
        brand="Apple", product_name=name,
        storage=storage, color=color
    )

def test_same_variant_matches():
    assert score(p("Apple iPhone 16 128GB Black"), p("آیفون 16 128 گیگ مشکی")) > 70

def test_storage_conflict_does_not_match():
    assert score(p("iPhone 16 128GB"), p("iPhone 16 256GB", storage="256GB")) == 0

def test_ch_a_and_cha_variants_match():
    a = p("iPhone 17 256GB CH/A Non Active")
    b = p("iPhone 17 256GB CHA NonActive")
    assert score(a, b) >= 90
