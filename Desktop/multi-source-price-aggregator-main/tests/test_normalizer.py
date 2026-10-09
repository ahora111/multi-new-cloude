from core.normalizer import normalize_text, normalize_capacity

def test_persian_arabic_normalization():
    assert normalize_text("آیفون 16  128 گیگ") == "iphone 16 128 gb"

def test_capacity():
    assert normalize_capacity("128 گیگابایت") == "128gb"
