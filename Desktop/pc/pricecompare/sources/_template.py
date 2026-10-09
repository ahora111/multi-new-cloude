"""Template for a NEW source. Copy to sources/my_shop.py, then register it in config/sources.yaml:

  - name: my_shop
    class: pricecompare.sources.my_shop:MyShopSource     # instead of `type:`
    currency_unit: toman            # DECLARE the raw unit of the site (toman | rial)
    min_expected_products: 20

Nothing in core/ needs to change.
"""
from .base import Source


class MyShopSource(Source):
    type_name = "my_shop"

    def records(self, watchlist):
        # Fetch with self.http.get(url) (rate limit, retries, cache, auth are handled) or self.read(path).
        # Return a list of dicts: id, title, price, stock, url, image, color, storage, ram, brand, extra
        # Prefer an official/JSON endpoint over HTML, and HTML over a browser (Playwright).
        return []
