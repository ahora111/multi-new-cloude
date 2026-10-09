# V2 Real Integration Notes

این نسخه واقعاً از منطق دو پروژه ارسالی استفاده می‌کند؛ نه Adapter ساختگی.

## Eways
`eway-bot-main-fixed-v2/main.py` به عنوان `sources/vendor_legacy/eways_legacy.py` منتقل شده و Adapter جدید این توابع واقعی را صدا می‌زند:
- `login_eways`
- `get_and_parse_categories`
- `parse_selected_ids_string`
- `get_selected_categories_according_to_selection`
- `get_products_from_category_page`
- `condense_products_to_leaf`
- `enrich_products_with_details`

بنابراین مسیر واقعی Eways شامل login، category selection، HTML/Lazy pagination و detail/spec extraction است.

## Hamrahtel
`laptop.hamrahtel-v2/src/scraper.py` به `sources/vendor_legacy/hamrahtel_scraper.py` منتقل شده و Adapter مستقیماً `fetch_all_products()` واقعی را استفاده می‌کند.

## تفاوت مهم با پروژه‌های قبلی
قیمت خام Sourceها وارد Core می‌شود. افزایش قیمت 1.5% و سایر markupهای پروژه Hamrahtel در لایه Source اعمال نشده‌اند، چون در سیستم جدید ابتدا باید قیمت خام Eways و Hamrahtel با هم مقایسه شوند. Markup باید بعد از انتخاب بهترین Source و در Destination اعمال شود.

## وضعیت تست
- `compileall`: موفق
- تست‌های Core: 6/6 موفق
- اتصال زنده به Eways/Hamrahtel در محیط ساخت اجرا نشده، چون این کار نیازمند credential واقعی و دسترسی شبکه به سایت‌هاست.
