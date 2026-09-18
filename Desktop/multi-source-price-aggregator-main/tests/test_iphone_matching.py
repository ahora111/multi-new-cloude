from core.models import SourceProduct
from core.matcher import match_products, score
from core.pricing import choose_lowest


def iphone(source, name, color, price, currency='IRT'):
    return SourceProduct(
        source=source, source_product_id=source, brand='Apple',
        product_name=name, model=name, color=color, price=price,
        stock='IN_STOCK', currency=currency,
    )


def test_iphone_17_ch_a_non_active_variants_match_and_convert_price():
    ht = iphone('hamrahtel', 'iPhone 17 256GB CH/A Non Active', 'Mist Blue', 348_990_000)
    ew = iphone('eways', 'iPhone 17 256GB CHA NonActive', 'blue', 3_495_000_000)
    canonicals, status = match_products([ht, ew])
    assert len(canonicals) == 1
    assert len(canonicals[0].source_products) == 2
    assert score(ht, ew) >= 90

    # Eways normalization is tested at the source boundary in test_eways_price.
    choose_lowest(canonicals[0])
    assert canonicals[0].variant_results['blue']['best_source'] == 'hamrahtel'


def test_color_is_not_base_identity():
    a = iphone('a', 'iPhone 17 256GB CH/A Non Active', 'black', 349_000_000)
    b = iphone('b', 'iPhone 17 256GB CH/A Non Active', 'blue', 348_990_000)
    canonicals, _ = match_products([a, b])
    assert len(canonicals) == 1
    assert len(canonicals[0].source_products) == 2
