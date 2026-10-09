# گزارش تغییرات V2-HOURLY-DELIVERY-PRICE-ALERTS

نسخه‌ی قبلی کامل حفظ شده است؛ همه‌ی تغییرات **افزودنی و ماژولار** هستند. هیچ روش استخراج منبعی
تغییر نکرده و هیچ قابلیتی حذف نشده است. مجموعه تست‌ها: از ۱۸۸ به **۲۴۰ تست پاس‌شده** رسید (۱ تست live به‌صورت پیش‌فرض deselect است).

## فایل‌های جدید

| فایل | شرح |
|---|---|
| `pricecompare/delivery.py` | موتور بازه‌ی سفارش/تحویل هر منبع: cut-off، چند بازه در روز، روزهای کاری، تعطیلات، Asia/Tehran، برچسب «تقریبی»، هزینه‌ی ارسال جدا |
| `config/delivery.yaml` | تنظیمات سفارش/تحویل منابع (نمونه/آفلاین) — قابل ویرایش توسط کاربر |
| `config.real/delivery.yaml` | تنظیمات سفارش/تحویل منابع واقعی (همه تخمینی تا تایید فروشنده) |
| `docs/DELIVERY_CONFIG_FA.md` | راهنمای قدم‌به‌قدم تنظیم سفارش/تحویل |
| `tests/test_delivery.py` | ۱۱ تست: قبل/دقیقاً در/بعد از cut-off، جمعه و تعطیلات، همان‌روز/روز بعد، بازه‌های متعدد، نامشخص، استقلال منابع، برچسب تقریبی، هزینه ارسال، اتصال به runner |
| `tests/test_price_alerts_v2.py` | ۹ تست: ثبت پایه، کاهش/افزایش با مبلغ و درصد و زمان‌ها، فرمول `((جدید-قدیم)/قدیم)×100`، آستانه، سابقه‌ی کهنه، بهترین قیمت بازار، dedup تلگرام، ثبت تغییرات زیر حدنصاب |
| `tests/test_cycle_v2.py` | ۸ تست: متادیتای چرخه، موازی‌بودن واقعی، جداسازی خطا، تفکیک ناقص/ناموفق، «داده قدیمی» و عدم برندگی قیمت کهنه، snapshot/از کش با حفظ زمان استخراج، جلوگیری از چرخه‌ی هم‌زمان، ماندگاری وضعیت منابع |
| `tests/test_fastest_cheapest.py` | ۷ تست: سریع‌ترین با تساوی→ارزان‌تر، اختلاف زمان/قیمت، نامشخص، «قیمت دریافت نشد»، منبع ناموفق، انتها-به-انتها |
| `tests/test_sorting_v2.py` | ۵ تست: نزولی بودن در JSON/CSV/MD/تلگرام، رنگ‌های نزولی، محصولات بی‌قیمت در انتها، تساوی پایدار، قیمت مرجع |
| `tests/test_telegram_v2.py` | ۷ تست: یک عنوان برای هر محصول، همه‌ی رنگ‌ها زیر عنوان، قیمت همه‌ی منابع کنار هر رنگ، شفافیت منبع ناقص، پیام هشدار مستقل، بدون حذف بی‌صدای پیام طولانی |
| `tests/test_new_source_v2.py` | ۵ تست: ورود منبع جدید به چرخه با فقط config، تحویل مستقل، غیرفعال‌سازی بدون پاک‌شدن تاریخچه، جداسازی خطا، آداپتور اختصاصی بدون تغییر هسته |
| `CHANGELOG_V2.md` | همین گزارش |

## فایل‌های تغییریافته

| فایل | تغییرات |
|---|---|
| `pricecompare/config.py` | کلیدهای جدید: `cycle_interval_minutes` (پیش‌فرض ۶۰)، `cycle_max_workers`، `timezone`، `price_alert_drop_pct`، `price_alert_market_beat_pct`، `vendor_price_compare_max_hours`، `source_state_file`، `source_snapshots_dir`، `alerts_file`، `telegram_alerts_enabled`، `telegram_alert_state_file`، `telegram_report_times`، `telegram_report_grace_minutes`، `telegram_report_state_file` + اعتبارسنجی سخت‌گیرانه (کلید ناشناخته = خطا، مثل قبل) |
| `pricecompare/runner.py` | چرخه‌ی مشترک با استخراج **موازی** (ThreadPoolExecutor؛ هر منبع HttpClient خودش → محدودیت نرخ هر سایت حفظ می‌شود)؛ متادیتای چرخه (شروع/پایان/زمان واقعی استخراج هر منبع)؛ وضعیت‌های «موفق/ناقص/ناموفق/داده قدیمی/از کش» + `status_fa`؛ ذخیره‌ی وضعیت منابع؛ snapshot برای `min_fetch_interval_minutes`؛ محاسبه‌ی تحویل و انتخاب سریع‌ترین + ارزان‌ترین برای هر رنگ؛ `deltas`؛ علامت‌گذاری مقایسه‌ی ناقص؛ تشخیص تغییرات قیمت به تفکیک منبع و هشدارها؛ مرتب‌سازی نزولی مشترک؛ ارسال مستقل هشدار و گزارش زمان‌بندی‌شده‌ی تلگرام |
| `pricecompare/history.py` | ثبت `source_prices` (قیمت معتبر هر فروشنده به تفکیک رنگ) در تاریخچه؛ `detect_changes` (کاهش/افزایش/بهترین بازار/ثبت پایه با مبلغ، درصد، زمان قبلی/جدید)؛ `append_alerts` (لاگ append-only همه‌ی تغییرات)؛ `unsent_alerts` (جلوگیری از هشدار تکراری)؛ توابع قبلی بدون تغییر |
| `pricecompare/pricing.py` | `fetched_at` در خروجی هر offer؛ `display_title` (عنوان استاندارد شامل برند)؛ `reference_price`، `sort_products`، `sort_variants`؛ `BRAND_PRETTY` |
| `pricecompare/report.py` | حذف تعریف‌های تکراری موجود (`build_telegram` و `write_all` دوبار تعریف شده بودند)؛ قالب V2 تلگرام: یک عنوان، رنگ‌ها با ایموجی/نام فارسی، قیمت همه‌ی منابع کنار هر رنگ، خط هشدار 📉/🏷️ کنار رنگ، خط سریع‌ترین ارسال 🚚 + هزینه ارسال، «قیمت دریافت نشد»، مهر زمان تهران، پیام فرصت‌های خرید چرخه؛ `build_alert_messages`؛ MD و CSV گسترش‌یافته (ستون‌های جدید انتهای CSV برای سازگاری)؛ `_line` قبلی بدون تغییر (تست دقیق دارد) |
| `pricecompare/cli.py` | دستور `watch` (چرخه‌ی ساعتی خودکار با `--cycles`) و دستور `delivery` (نمایش cut-off و تحویل فعلی هر منبع) |
| `config/settings.yaml` و `config.real/settings.yaml` | کلیدهای V2 با مقادیر پیش‌فرض مستندشده |
| `requirements.txt` | `tzdata>=2024.1` |
| `tests/conftest_helpers.py` | مسیر مطلق فایل‌های state جدید در سندباکس تست |
| `tests/test_repo_hygiene.py` | `config/delivery.yaml` و `config.real/delivery.yaml` به فایل‌های ضروری اضافه شد |
| `tests/test_runner_integration.py` | یک تست به ترتیب قدیمی products[0] وابسته بود؛ حالا محصول را با id می‌یابد (هدف تست حفظ شده؛ مرتب‌سازی نزولی الزام §۹ است) |
| `README.md` / `docs/ADD_SOURCE.md` | مستندات V2 |

## حفظ قابلیت‌های قبلی

- روش استخراج همه‌ی منابع (Eways, Hamrahtel, Farnaa, ExonTel, KasraPars, Digikala B2B + generic json/html/csv) **دست‌نخورده**.
- منطق تطبیق، outlier، scale-check، discovery، color_merge، force_match/split، lock و کدهای خروجی قبلی همه سر جای خود هستند.
- خروجی‌های قبلی (`output.json`, `report.csv`, `report.md`, `matching_report.json`, `run_summary.json`) همان ساختار را دارند + فیلدهای افزودنی.
- خطای «۲ تعریف تکراری در report.py» رفع شد (رفع خطای واقعی، نه پنهان‌کردن آن).
