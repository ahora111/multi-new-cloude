from .base import Source
from .vendor_legacy import hamrahtel_scraper as scraper
from core.models import SourceProduct
from config.settings import settings
import re

class HamrahtelSource(Source):
    name = 'hamrahtel'

    def fetch(self):
        products, ok = scraper.fetch_all_products(settings)
        if not products:
            raise RuntimeError('Hamrahtel returned zero products')
        result = []
        for p in products:
            raw_price = re.sub(r'[^0-9]', '', p.price or '')
            price = float(raw_price) if raw_price else None
            result.append(SourceProduct(
                source=self.name,
                source_product_id=f'{p.brand}|{p.model}|{p.color}|{p.price}',
                brand=p.brand,
                product_name=' '.join(x for x in [p.brand, p.model] if x),
                model=p.model,
                variant=p.color,
                color=p.color,
                price=price,
                stock='IN_STOCK',
                currency='IRT',
                category='unknown',
            ))
        return result
