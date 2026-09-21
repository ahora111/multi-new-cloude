from pricecompare.debugpage import PRICE_RE, is_price_line, norm_line, numbered


def test_price_detection_handles_persian_digits_and_separators():
    assert is_price_line("۴۹٬۷۹۹٬۰۰۰") and is_price_line("49,799,000 تومان") and is_price_line("34390000")
    assert not is_price_line("Galaxy A17 128GB") and not is_price_line("%3") and not is_price_line("افزودن")
    assert PRICE_RE.search("از ۳۴٬۵۰۰٬۰۰۰ تومان".translate(str.maketrans("۰۱۲۳۴۵۶۷۸۹", "0123456789")))


def test_numbered_slice_and_line_normalisation():
    assert norm_line("  ۴۹  ۷۹۹ ") == "49 799"
    out = numbered(["a"] * 20 + ["x", "49,799,000"], 21, n=3, context=1)
    assert out[0].startswith("  20 |") and out[-1].endswith("49,799,000")
