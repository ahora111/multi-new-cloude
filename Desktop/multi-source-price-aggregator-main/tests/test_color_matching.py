from core.models import SourceProduct
from core.normalizer import normalized_product
from core.matcher import score
from sources.vendor_legacy.hamrahtel_scraper import parse_card_variants


def test_hamrahtel_multi_color_card_creates_one_variant_per_price():
    products = parse_card_variants([
        "Galaxy A17 128GB RAM 4GB",
        "مشخصات کالا",
        "برند: سامسونگ",
        "مشکی",
        "49٬799٬000تومانءء",
        "خاکستری",
        "51٬099٬000تومانءء",
        "آبی روشن",
        "50٬899٬000تومانءء",
    ])
    assert len(products) == 3
    assert [p.color for p in products] == ["مشکی", "خاکستری", "آبی روشن"]
    assert [p.price for p in products] == ["49٬799٬000", "51٬099٬000", "50٬899٬000"]


def test_cross_source_a17_black_matches():
    hamrahtel = normalized_product(SourceProduct(
        source="hamrahtel", source_product_id="1", brand="Galaxy",
        product_name="Galaxy A17 128GB RAM 4GB", model="A17 128GB RAM 4GB",
        storage="", ram="", color="مشکی", price=49799000, stock="IN_STOCK"
    ))
    eways = normalized_product(SourceProduct(
        source="eways", source_product_id="4285|1523720", brand="Samsung",
        product_name="Samsung Galaxy A17 (RAM 4) ظرفیت 128GB - مشکی (ویتنام)",
        model="Galaxy A17 (RAM 4) ظرفیت 128GB - مشکی (ویتنام)",
        price=49800000, stock="IN_STOCK"
    ))
    assert hamrahtel.color == "black"
    assert eways.color == "black"
    assert hamrahtel.storage == "128gb"
    assert eways.storage == "128gb"
    assert hamrahtel.ram == "4gb"
    assert eways.ram == "4gb"
    assert score(hamrahtel, eways) >= 70


def test_different_colors_do_not_match():
    a = normalized_product(SourceProduct(
        source="a", source_product_id="1", brand="Samsung",
        product_name="Samsung Galaxy A17 128GB RAM 4GB مشکی", color="مشکی"
    ))
    b = normalized_product(SourceProduct(
        source="b", source_product_id="2", brand="Samsung",
        product_name="Samsung Galaxy A17 128GB RAM 4GB خاکستری", color="خاکستری"
    ))
    assert score(a, b) == 0.0


def test_three_hamrahtel_colors_and_one_eways_black_are_one_canonical_with_per_color_price():
    from core.matcher import match_products
    from core.pricing import choose_lowest
    items = []
    for color, price in [("مشکی", 49799000), ("خاکستری", 51099000), ("آبی روشن", 50899000)]:
        items.append(SourceProduct(source="hamrahtel", source_product_id=color, brand="Galaxy",
            product_name="Galaxy A17 128GB RAM 4GB", model="A17 128GB RAM 4GB",
            color=color, price=price, stock="IN_STOCK"))
    items.append(SourceProduct(source="eways", source_product_id="4285|1523720", brand="Samsung",
        product_name="Samsung Galaxy A17 (RAM 4) ظرفیت 128GB - مشکی (ویتنام)",
        model="Galaxy A17 (RAM 4) ظرفیت 128GB - مشکی (ویتنام)", price=49800000, stock="IN_STOCK"))
    canonicals, status = match_products(items)
    assert len(canonicals) == 1
    choose_lowest(canonicals[0])
    assert canonicals[0].variant_results["black"]["source"] == "hamrahtel"
    assert canonicals[0].variant_results["black"]["price"] == 49799000
    assert canonicals[0].variant_results["gray"]["source"] == "hamrahtel"
    assert canonicals[0].variant_results["light blue"]["source"] == "hamrahtel"


def test_cross_source_matching_is_independent_of_scrape_order_and_compares_all_sources():
    from core.matcher import match_products
    from core.pricing import choose_lowest
    h = SourceProduct(source="hamrahtel", source_product_id="h", brand="Galaxy",
        product_name="Galaxy A17 128GB RAM 4GB", model="A17 128GB RAM 4GB",
        color="مشکی", price=49799000, stock="IN_STOCK")
    e = SourceProduct(source="eways", source_product_id="e", brand="Samsung",
        product_name="گوشی موبایل Samsung مدل Galaxy A17 (RAM 4) ظرفیت 128GB - مشکی (ویتنام)",
        model="Galaxy A17 (RAM 4) ظرفیت 128GB - مشکی (ویتنام)",
        price=49800000, stock="IN_STOCK")
    for items in ([h, e], [e, h]):
        canonicals, _ = match_products(items)
        assert len(canonicals) == 1
        assert {p.source for p in canonicals[0].source_products} == {"hamrahtel", "eways"}
        choose_lowest(canonicals[0])
        assert canonicals[0].variant_results["black"]["source"] == "hamrahtel"
        assert canonicals[0].best_price == 49799000
