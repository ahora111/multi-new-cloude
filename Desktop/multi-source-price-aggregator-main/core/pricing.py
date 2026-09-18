from statistics import median
from .models import CanonicalProduct, SourceProduct
from .normalizer import normalized_product

VALID_STOCK = {"IN_STOCK", "AVAILABLE", "AVAILABLE_NOW"}

def valid_price(p: SourceProduct) -> bool:
    return p.price is not None and float(p.price) > 0 and p.stock in VALID_STOCK

def choose_lowest(product: CanonicalProduct):
    # Normalize direct/manual SourceProduct fixtures as well as scraped data.
    for p in product.source_products:
        normalized_product(p)
    candidates = [p for p in product.source_products if valid_price(p)]
    product.variant_results = {}
    if not candidates:
        product.best_price = None
        product.best_source = None
        product.best_url = None
        product.best_stock = None
        return product

    # Group by normalized color. Empty color is its own variant, so an
    # uncoloured offer is never silently treated as every coloured offer.
    groups = {}
    for p in candidates:
        key = (p.color or p.variant or "").strip() or "__no_color__"
        groups.setdefault(key, []).append(p)

    overall = []
    for variant, items in groups.items():
        values = [float(p.price) for p in items]
        med = median(values)
        filtered = [p for p in items if float(p.price) <= med * 3.0] or items
        best = min(filtered, key=lambda x: float(x.price))
        result = {
            "variant": "" if variant == "__no_color__" else variant,
            "price": float(best.price),
            "best_price": float(best.price),
            "source": best.source,
            "best_source": best.source,
            "url": best.url,
            "best_url": best.url,
            "stock": best.stock,
            "best_stock": best.stock,
            "offers": [
                {
                    "source": p.source, "price": float(p.price),
                    "url": p.url, "stock": p.stock,
                    "color": p.color,
                } for p in items
            ],
        }
        product.variant_results[variant] = result
        overall.append(best)

    # Preserve the legacy top-level fields as the cheapest valid variant
    # overall, while Telegram exposes every per-color result.
    best = min(overall, key=lambda x: float(x.price))
    product.best_price = float(best.price)
    product.best_source = best.source
    product.best_url = best.url
    product.best_stock = best.stock
    return product
