from pricecompare.extract import Extractor, parse_price

ex = Extractor()


def test_persian_title_attributes():
    a = ex.parse("گوشی موبایل Samsung مدل Galaxy A17 (RAM 4) ظرفیت 128GB - مشکی (ویتنام)")
    assert (a.brand, a.core, a.storage_gb, a.ram_gb, a.color, a.region) == ("samsung", ["galaxy", "a17"], 128, 4, "black", "vietnam")


def test_tiers_and_persian_tier_words():
    assert ex.parse("iPhone 17 Pro Max 1TB").tiers == ["max", "pro"]
    assert ex.parse("iPhone 17 Pro Max 1TB").storage_gb == 1024
    assert ex.parse("آیفون 17 پرو 256 گیگ").tiers == ["pro"]
    assert ex.parse("Galaxy S25+ 256GB").tiers == ["plus"]


def test_region_condition_network_ram_slash_format():
    a = ex.parse("iPhone 17 256GB CH/A Non Active")
    assert (a.region, a.condition) == ("cha", "nonactive")
    b = ex.parse("Redmi Note 14 Pro 5G 8/256 مشکی")
    assert (b.network, b.ram_gb, b.storage_gb) == ("5g", 8, 256)


def test_digit_suffix_stays_in_model_core():
    assert ex.parse("iPhone 17e 256GB").core == ["iphone", "17e"]


def test_colour_synonyms_and_explicit_field_wins():
    assert ex.parse("iPhone 17 256GB Mist Blue").color == "blue"
    assert ex.parse("iPhone 17 256GB", raw_color="مشکی").color == "black"
    assert ex.parse("iPhone 17 256GB", raw_color="Cosmic Teal!").color == "cosmic teal"


def test_parse_price_formats():
    assert parse_price("۴۹٬۷۹۹٬۰۰۰ تومان") == 49799000
    assert parse_price("23.190.000") == 23190000
    assert parse_price("641,000,000 ریال") == 641000000
    assert parse_price(4.9e7) == 4.9e7
    assert parse_price("ناموجود") is None and parse_price("") is None and parse_price(None) is None
