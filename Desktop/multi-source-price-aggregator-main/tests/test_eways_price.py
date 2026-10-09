from sources.eways import EwaysSource


def test_eways_rial_price_is_normalized_to_toman(monkeypatch):
    src = EwaysSource(username='u', password='p')

    class Legacy:
        pass

    import sources.eways as module
    monkeypatch.setattr(module.legacy, 'login_eways', lambda u, p: object())
    monkeypatch.setattr(module.legacy, 'get_and_parse_categories', lambda s: [{'id': 1}])
    monkeypatch.setattr(module.legacy, 'init_category_index_global', lambda cats: None)
    monkeypatch.setattr(module.legacy, 'parse_selected_ids_string', lambda value: [])
    monkeypatch.setattr(module.legacy, 'get_selected_categories_according_to_selection', lambda parsed, cats: ([{'id': 1}], None))
    monkeypatch.setattr(module.legacy, 'get_products_from_category_page', lambda *args: [{'id': '1', 'category_id': 1, 'name': 'Apple iPhone 17 256GB CHA NonActive', 'price': '3495000000', 'stock': 1}])
    monkeypatch.setattr(module.legacy, 'condense_products_to_leaf', lambda rows, cats: rows)
    monkeypatch.setattr(module.legacy, 'enrich_products_with_details', lambda *args: None)
    monkeypatch.setattr(module.legacy, 'CATEGORY_NAME', {1: 'mobile'})
    monkeypatch.setattr(module.legacy, 'PRODUCT_DETAIL_URL_TEMPLATE', 'https://example/{cat_id}/{product_id}')

    products = src.fetch()
    assert products[0].price == 349_500_000
    assert products[0].attributes['raw_price_irt'] == 3_495_000_000
