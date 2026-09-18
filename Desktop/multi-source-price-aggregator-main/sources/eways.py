from .base import Source
from .vendor_legacy import eways_legacy as legacy
from core.models import SourceProduct
from core.normalizer import infer_brand, normalize_text
import re

class EwaysSource(Source):
    name = 'eways'

    def __init__(self, username=None, password=None, selected_ids=None):
        self.username = username or legacy.EWAYS_USERNAME
        self.password = password or legacy.EWAYS_PASSWORD
        self.selected_ids = selected_ids or __import__('os').environ.get('SELECTED_IDS_STRING') or '16777:all-allz'

    def fetch(self):
        session = legacy.login_eways(self.username, self.password)
        if not session:
            raise RuntimeError('Eways login failed')
        cats = legacy.get_and_parse_categories(session)
        if not cats:
            raise RuntimeError('Eways categories could not be loaded')
        legacy.init_category_index_global(cats)
        parsed = legacy.parse_selected_ids_string(self.selected_ids)
        scrape_categories, _ = legacy.get_selected_categories_according_to_selection(parsed, cats)
        if not scrape_categories:
            raise RuntimeError('No Eways categories selected')

        products_by_key = {}
        failed = 0
        for cat in scrape_categories:
            try:
                rows = legacy.get_products_from_category_page(
                    session, cat['id'], legacy.EWAYS_MAX_PAGES, 0.5
                )
                for row in rows:
                    key = f"{row.get('id')}|{row.get('category_id')}"
                    products_by_key[key] = row
            except Exception:
                failed += 1

        if failed and not products_by_key:
            raise RuntimeError('All Eways selected categories failed')

        canonical = legacy.condense_products_to_leaf(products_by_key, cats)
        # Reuse the source project's detail enrichment for new/selected products.
        if canonical:
            try:
                legacy.enrich_products_with_details(session, canonical, set(canonical.keys()))
            except Exception:
                # Details are enrichment; raw product data remains usable.
                pass

        result = []
        for pid, row in canonical.items():
            specs = row.get('specs') or {}
            name = row.get('name') or ''
            brand = infer_brand(name)
            normalized_name = normalize_text(name)
            model = normalized_name
            if brand:
                model = re.sub(rf"(?<!\w){re.escape(brand)}(?!\w)", " ", model)
                model = re.sub(r"\s+", " ", model).strip() or normalized_name
            barcode = ''
            sku = str(row.get('sku') or row.get('code') or '')
            for k, v in specs.items():
                lk = str(k).lower()
                if 'barcode' in lk or 'بارکد' in lk:
                    barcode = str(v)
                if not sku and ('sku' in lk or 'کد' in lk):
                    sku = str(v)
            storage = ''
            ram = ''
            color = ''
            for k, v in specs.items():
                lk = str(k).lower()
                if 'حافظه داخلی' in lk or 'storage' in lk or 'حافظه' == lk:
                    storage = str(v)
                elif 'ram' in lk or 'رم' in lk:
                    ram = str(v)
                elif 'رنگ' in lk or 'color' in lk:
                    color = str(v)
            stock = 'IN_STOCK' if int(row.get('stock') or 0) else 'OUT_OF_STOCK'
            try:
                raw_price = float(row.get('price') or 0)
                price = raw_price
                # Eways exposes IRT (rial); internal comparison values are toman.
                if price >= 1_000_000_000:
                    price /= 10.0
            except Exception:
                raw_price = None
                price = None
            result.append(SourceProduct(
                source=self.name,
                source_product_id=str(pid),
                brand=brand,
                product_name=name,
                price=price,
                stock=stock,
                url=legacy.PRODUCT_DETAIL_URL_TEMPLATE.format(
                    cat_id=row.get('detail_hint_cat_id') or row.get('category_id'),
                    product_id=pid
                ),
                image=row.get('image') or '',
                sku=sku,
                barcode=barcode,
                model=model,
                storage=storage,
                ram=ram,
                color=color,
                category=legacy.CATEGORY_NAME.get(row.get('category_id'), 'unknown'),
                currency='IRT',
                attributes={
                    'specs': specs,
                    'eways_category_id': row.get('category_id'),
                    'price_normalized_to_toman': True,
                    'raw_price_irt': raw_price,
                }
            ))
        if not result:
            raise RuntimeError('Eways returned zero products')
        return result
