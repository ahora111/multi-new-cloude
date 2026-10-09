import re
from rapidfuzz.fuzz import ratio, token_set_ratio
from .models import SourceProduct, CanonicalProduct
from .normalizer import normalize_text, normalized_product
from config.settings import settings

REGION_TOKENS = {
    "vietnam", "china", "india", "uae", "global", "eu", "europe", "usa",
    "ویتنام", "چین", "هند", "امارات"
}
GENERIC_MODEL_WORDS = {
    "phone", "mobile", "smartphone", "گوشی", "موبایل", "model", "مدل",
    "capacity", "storage", "memory", "ram", "حافظه", "رم", "ظرفیت",
    "gb", "tb", "گیگ", "گیگابایت", "5g", "4g"
}


def canonical_key(p: SourceProduct) -> str:
    p = normalized_product(p)
    base = _base_identity_text(p)
    parts = [p.brand, base, p.storage, p.ram]
    return "|".join(normalize_text(x) for x in parts if x)


def _remove_known(text: str, p: SourceProduct, include_color: bool = True) -> str:
    text = normalize_text(text)
    tokens = [p.brand, p.storage, p.ram, p.variant]
    if include_color:
        tokens.append(p.color)
    for token in tokens:
        token = normalize_text(token)
        if token:
            text = re.sub(rf"(?<!\w){re.escape(token)}(?!\w)", " ", text)
    # Remove region/version markers only from the model identity. They remain
    # separate attributes and can be used as hard constraints when both sides
    # explicitly provide them.
    for token in REGION_TOKENS:
        text = re.sub(rf"(?<!\w){re.escape(normalize_text(token))}(?!\w)", " ", text)
    text = re.sub(r"\b(?:ram|capacity|storage|memory|حافظه|رم|ظرفیت)\b", " ", text)
    # Keep standalone numbers because they can be part of model names (e.g. A17).
    # Storage/RAM are already represented by explicit fields and are handled separately.
    text = re.sub(r"\b(?:5g|4g)\b", " ", text)
    text = re.sub(r"[^\w\s.-]+", " ", text)
    words = [w for w in text.split() if w not in GENERIC_MODEL_WORDS]
    return " ".join(words).strip()


def _base_identity_text(p: SourceProduct) -> str:
    text = p.model or p.product_name
    return _remove_known(text, p, include_color=True)


def _same_known_specs(a: SourceProduct, b: SourceProduct) -> bool:
    for x, y in ((a.storage, b.storage), (a.ram, b.ram)):
        if x and y and x != y:
            return False
    # If both sides explicitly identify a region/version, don't mix them.
    a_region = _detect_region(a.product_name + " " + a.model)
    b_region = _detect_region(b.product_name + " " + b.model)
    if a_region and b_region and a_region != b_region:
        return False
    return True


def _detect_region(text: str) -> str:
    s = normalize_text(text)
    for token in REGION_TOKENS:
        t = normalize_text(token)
        if re.search(rf"(?<!\w){re.escape(t)}(?!\w)", s):
            return t
    return ""


def _base_score(a: SourceProduct, b: SourceProduct) -> float:
    a, b = normalized_product(a), normalized_product(b)
    if a.brand != b.brand or not _same_known_specs(a, b):
        return 0.0

    ta, tb = _base_identity_text(a), _base_identity_text(b)
    if not ta or not tb:
        return 0.0

    # The model identity is the primary signal. Full title similarity is only
    # a secondary signal because stores add very different boilerplate.
    model_score = token_set_ratio(ta, tb)
    title_score = token_set_ratio(a.product_name, b.product_name)
    return round(0.80 * model_score + 0.20 * title_score, 2)


def score(a: SourceProduct, b: SourceProduct) -> float:
    a, b = normalized_product(a), normalized_product(b)
    if a.barcode and b.barcode and a.barcode == b.barcode:
        return 100.0
    if a.sku and b.sku and a.sku == b.sku and a.brand == b.brand:
        return 98.0
    if a.brand != b.brand or not _same_known_specs(a, b):
        return 0.0
    if a.color and b.color and a.color != b.color:
        return 0.0

    base = _base_score(a, b)
    if base == 0:
        return 0.0
    # Same-color matches receive the base identity score plus a small title
    # confirmation bonus; different colors are intentionally handled as base
    # product matches elsewhere, never as the same priced variant.
    if a.color and b.color and a.color == b.color:
        return min(100.0, round(base + 5.0, 2))
    return base


def _pair_should_match(a: SourceProduct, b: SourceProduct) -> bool:
    # Products from the same source are never used to merge one another. We
    # need a cross-source comparison, not a single-source clustering pass.
    if a.source == b.source:
        return False
    s = score(a, b)
    return s >= settings.match_auto_threshold


def match_products(products: list[SourceProduct]):
    """Build canonicals from a cross-source comparison matrix.

    Every product from every enabled source is first normalized. We then
    compare source A against source B (and any additional source pairs), form
    connected product groups, and only after grouping calculate per-variant
    prices. This prevents the order in which sources were scraped from
    changing the result.
    """
    items = [normalized_product(p) for p in products]
    n = len(items)
    parent = list(range(n))
    rank = [0] * n

    def find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def union(x, y):
        x, y = find(x), find(y)
        if x == y:
            return
        if rank[x] < rank[y]:
            x, y = y, x
        parent[y] = x
        if rank[x] == rank[y]:
            rank[x] += 1

    matched_pairs = 0
    review_pairs = 0
    sources = sorted({p.source for p in items})
    for i in range(n):
        for j in range(i + 1, n):
            a, b = items[i], items[j]
            if a.source == b.source:
                # Same-source variants of the exact same base product belong to
                # one canonical group, but they are NOT price-comparison pairs.
                # Their colors/prices remain separate variants for pricing.
                s = _base_score(a, b)
                if s >= settings.match_auto_threshold:
                    union(i, j)
                continue

            # Cross-source comparison: every product from source A is compared
            # against every product from source B (and every other enabled
            # source pair), so scrape order can never decide the winner.
            s = score(a, b)
            if s >= settings.match_auto_threshold:
                union(i, j)
                matched_pairs += 1
            else:
                # Different colors are separate priced variants, but still
                # belong to the same base canonical product.
                base = _base_score(a, b)
                if base >= settings.match_auto_threshold:
                    union(i, j)
                elif s >= settings.match_review_threshold:
                    review_pairs += 1

    groups = {}
    for i, p in enumerate(items):
        groups.setdefault(find(i), []).append(p)

    canonicals = []
    for group in groups.values():
        # Stable representative: prefer the product with the richest identity
        # information, then deterministic source/id ordering.
        representative = max(
            group,
            key=lambda p: (
                bool(p.brand), bool(p.model), bool(p.storage), bool(p.ram),
                bool(p.color), len(p.product_name),
            ),
        )
        canonicals.append(CanonicalProduct(
            canonical_id=canonical_key(representative),
            brand=representative.brand,
            model=_base_identity_text(representative) or representative.model or representative.product_name,
            category=representative.category,
            attributes=representative.attributes,
            source_products=sorted(group, key=lambda p: (p.source, p.source_product_id)),
        ))

    # Count products that actually joined an existing cross-source group.
    matched_products = sum(max(0, len(g) - 1) for g in groups.values() if len({p.source for p in g}) > 1)
    return canonicals, {"matched": matched_products, "review": review_pairs}
