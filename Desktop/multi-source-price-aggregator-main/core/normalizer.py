import re
from .models import SourceProduct

ALIASES = {
    "آیفون": "apple", "iphone": "apple", "اپل": "apple", "apple": "apple", "galaxy": "samsung", "samsung": "samsung", "مشکی": "black", "سیاه": "black", "سفید": "white",
    "قرمز": "red", "آبی": "blue", "آبی روشن": "light blue", "آبی تیره": "dark blue",
    "سبز": "green", "خاکستری": "gray", "طوسی": "gray",
    "بنفش": "purple", "صورتی": "pink", "طلایی": "gold", "نقره ای": "silver", "نقره‌ای": "silver",
    "ویتنام": "vietnam", "چین": "china", "هند": "india", "امارات": "uae",
    "گیگابایت": "gb", "گیگ": "gb", "ترابایت": "tb",
}

ARABIC_MAP = str.maketrans({
    "ي": "ی", "ى": "ی", "ك": "ک",
    "ۀ": "ه", "ة": "ه",
})

def normalize_text(value: str) -> str:
    value = str(value or "").translate(ARABIC_MAP).lower()
    value = value.replace("‌", " ")
    for src, dst in sorted(ALIASES.items(), key=lambda item: len(item[0]), reverse=True):
        value = value.replace(src, dst)
    value = re.sub(r"[,_|/\\\\()\\[\\]{}:;]+", " ", value)
    value = re.sub(r"\bch\s*/?\s*a\b", "cha", value)
    value = re.sub(r"\bnon[ -]*active\b", "nonactive", value)
    value = re.sub(r"\s+", " ", value).strip()
    return value



BRAND_ALIASES = {
    "samsung": "samsung", "galaxy": "samsung",
    "apple": "apple", "iphone": "apple",
    "honor": "honor", "huawei": "huawei",
    "xiaomi": "xiaomi", "شیائومی": "xiaomi", "redmi": "xiaomi", "poco": "xiaomi",
    "oneplus": "oneplus", "nothing": "nothing",
    "google": "google", "pixel": "google",
    "nokia": "nokia", "motorola": "motorola", "sony": "sony",
    "tcl": "tcl", "realme": "realme", "infinix": "infinix",
    "tecno": "tecno", "vivo": "vivo", "oppo": "oppo",
    "asus": "asus", "lenovo": "lenovo",
}

def infer_brand(value: str) -> str:
    s = normalize_text(value)
    for token in sorted(BRAND_ALIASES, key=len, reverse=True):
        if re.search(rf"(?<!\w){re.escape(normalize_text(token))}(?!\w)", s):
            return BRAND_ALIASES[token]
    return ""

COLOR_TOKENS = (
    "black", "white", "red", "blue", "light blue", "dark blue", "green",
    "gray", "purple", "pink", "gold", "silver", "مشکی", "سفید", "قرمز",
    "آبی", "آبی روشن", "آبی تیره", "سبز", "خاکستری", "طوسی", "بنفش",
    "صورتی", "طلایی", "نقره ای", "نقره‌ای",
)

def infer_color(value: str) -> str:
    s = normalize_text(value)
    # Prefer longer colors first (e.g. light blue before blue).
    for token in sorted(COLOR_TOKENS, key=len, reverse=True):
        token_n = normalize_text(token)
        if re.search(rf"(?<!\w){re.escape(token_n)}(?!\w)", s):
            return token_n
    return ""

def infer_capacity(value: str, kind: str) -> str:
    s = normalize_text(value)
    if kind == "storage":
        # Prefer an explicit capacity that is not immediately marked as RAM.
        matches = list(re.finditer(r"(\d+(?:\.\d+)?)\s*(gb|tb)", s))
        if not matches:
            return ""
        # When RAM is present, the first number can be RAM; storage is usually
        # the larger capacity or the one nearest a storage keyword.
        for m in matches:
            before = s[max(0, m.start()-12):m.start()]
            if not re.search(r"(?:ram|رم)$", before.strip()):
                return f"{m.group(1)}{m.group(2)}"
        return f"{matches[-1].group(1)}{matches[-1].group(2)}"
    m = re.search(r"(?:ram|رم)\s*(?:[:=/-]\s*)?(\d+(?:\.\d+)?)\s*(gb|tb)?", s)
    if m:
        return f"{m.group(1)}{m.group(2) or 'gb'}"
    # Common title form: "RAM 4".
    return ""

def normalize_capacity(value: str) -> str:
    s = normalize_text(value)
    m = re.search(r"(\d+(?:\.\d+)?)\s*(gb|tb)", s)
    if not m:
        return s
    return f"{m.group(1)}{m.group(2)}"

def normalized_product(p: SourceProduct) -> SourceProduct:
    p.brand = normalize_text(p.brand)
    p.product_name = normalize_text(p.product_name)
    inferred_brand = infer_brand(p.product_name)
    if inferred_brand:
        p.brand = inferred_brand
    p.model = normalize_text(p.model)
    p.variant = normalize_text(p.variant)
    p.storage = normalize_capacity(p.storage)
    p.ram = normalize_capacity(p.ram)
    p.color = normalize_text(p.color)
    # Normalize explicit color names too (e.g. "mist blue" -> "blue") so
    # equivalent color variants can be compared across sources. Keep the
    # longest known color first (light/dark blue before blue).
    if p.color:
        inferred = infer_color(p.color)
        if inferred:
            p.color = inferred

    # Some sources put RAM/storage/color only in the title. Infer missing
    # variant attributes so equivalent products can be matched across stores.
    if not p.storage:
        p.storage = infer_capacity(p.product_name, "storage")
    if not p.ram:
        p.ram = infer_capacity(p.product_name, "ram")
    if not p.color:
        p.color = infer_color(p.product_name)
    if not p.variant and p.color:
        p.variant = p.color
    p.barcode = re.sub(r"\D", "", p.barcode or "")
    p.category = normalize_text(p.category)

    # Eways exposes prices in rial while the comparison pipeline uses toman.
    # Normalize direct SourceProduct instances here as well as at the source
    # boundary, but mark converted records so they are never divided twice.
    if p.source == "eways" and float(p.price or 0) > 0:
        marker = p.attributes.get("price_normalized_to_toman")
        if not marker:
            # Eways legacy feeds can expose either already-toman values or
            # rial values. A rial value in the high 10^9 range is the known
            # feed representation that needs /10 conversion; lower values
            # are kept compatible with existing Eways normalized fixtures.
            if float(p.price) >= 1_000_000_000:
                p.price = float(p.price) / 10.0
            p.attributes["price_normalized_to_toman"] = True
    return p
