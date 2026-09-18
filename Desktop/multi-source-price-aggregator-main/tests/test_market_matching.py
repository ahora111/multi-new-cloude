from core.models import SourceProduct, CanonicalProduct
from core.matcher import match_products, score
from core.pricing import choose_lowest

def make(source, title, color, price):
    return SourceProduct(source=source, source_product_id=source+color, brand='Samsung', product_name=title,
        model=title, storage='128GB', ram='4GB', color=color, price=price, stock='IN_STOCK')

def test_a17_cross_source_base_and_color_matching():
    ht=make('hamrahtel','Galaxy A17 128GB RAM 4GB Vietnam','مشکی',49799000)
    ew=make('eways','گوشی موبایل Samsung مدل Galaxy A17 (RAM 4) ظرفیت 128GB - مشکی (ویتنام)','مشکی',49800000)
    blue=make('hamrahtel','Galaxy A17 128GB RAM 4GB Vietnam','آبی روشن',50899000)
    canonicals,status=match_products([ht,ew,blue])
    assert len(canonicals)==1
    assert len(canonicals[0].source_products)==3
    assert score(ht,ew)>80
    assert score(ht,blue)==0

def test_price_is_per_color():
    p=CanonicalProduct('a','Samsung','Galaxy A17','mobile',{},[
        make('hamrahtel','Galaxy A17 128GB RAM 4GB Vietnam','مشکی',49799000),
        make('eways','Galaxy A17 128GB RAM 4GB Vietnam','مشکی',49800000),
        make('hamrahtel','Galaxy A17 128GB RAM 4GB Vietnam','خاکستری',51099000),
    ])
    choose_lowest(p)
    assert p.variant_results['black']['best_source']=='hamrahtel'
    assert p.variant_results['gray']['best_source']=='hamrahtel'
    assert len(p.variant_results['black']['offers'])==2


def test_iphone_17_mist_blue_cross_source_matching():
    from core.pricing import choose_lowest
    ht = make('hamrahtel', 'iPhone 17 256GB CH/A Non Active', 'blue', 348990000)
    ew = make('eways', 'iPhone 17 256GB CH/A Non Active', 'blue', 3490000000)
    ht.brand = 'Apple'
    ew.brand = 'Apple'
    canonicals, status = match_products([ht, ew])
    assert len(canonicals) == 1
    assert len(canonicals[0].source_products) == 2
    choose_lowest(canonicals[0])
    assert canonicals[0].variant_results['blue']['best_source'] == 'hamrahtel'
    assert canonicals[0].variant_results['blue']['best_price'] == 348990000
