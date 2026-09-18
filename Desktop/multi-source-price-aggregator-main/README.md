# Multi-Source Product Aggregator V2 — Eways + Hamrahtel

نسخه V2 واقعی پروژه، با انتقال منطق استخراج دو پروژه ارسالی به معماری جدید.

## Sourceهای واقعی

### Eways
منطق پروژه `eway-bot-main-fixed-v2` مستقیماً در `sources/vendor_legacy/eways_legacy.py` نگهداری شده و Adapter جدید `sources/eways.py` آن را به مدل استاندارد Core تبدیل می‌کند.

این Adapter از موارد اصلی پروژه قبلی استفاده می‌کند:
- Login مقاوم
- Cookie اختیاری
- Retry شبکه
- دریافت دسته‌بندی
- SELECTED_IDS_STRING
- HTML product extraction
- Lazy loading
- Pagination
- Product details/specs
- انتخاب leaf/deepest category
- rate limiting جزئیات

### Hamrahtel
منطق `src/scraper.py` پروژه `laptop.hamrahtel-v2` در `sources/vendor_legacy/hamrahtel_scraper.py` منتقل شده و Adapter `sources/hamrahtel.py` خروجی آن را به مدل استاندارد تبدیل می‌کند.

حفظ شده:
- Playwright
- چهار دسته mobile/laptop/tablet/console
- scroll
- card extraction
- legacy fallback
- retry
- dedupe
- headless browser

## Pipeline

`Eways + Hamrahtel -> Normalize -> Match -> Canonical Product -> Lowest Valid Price -> Destination`

قیمت خام Sourceها مقایسه می‌شود. Markup قبلی Hamrahtel عمداً وارد مرحله Source نشده تا مقایسه قیمت بین منابع واقعی و منصفانه باشد؛ markup باید در Destination Pricing اضافه شود.

## اجرا

```bash
pip install -r requirements.txt
playwright install chromium
python main.py
```

### GitHub Actions (Eways + Hamrahtel واقعی)

Workflow فایل `.github/workflows/sync.yml` مستقیماً از پوشه `v2real` اجرا می‌شود و هر دو Source واقعی را فعال می‌کند. در GitHub باید این موارد تنظیم شوند:

- Repository Secret: `EWAYS_USERNAME`
- Repository Secret: `EWAYS_PASSWORD`
- Repository Variable اختیاری: `SELECTED_IDS_STRING`

Chromium و dependencyهای لازم Playwright نیز در Runner نصب می‌شوند. خروجی واقعی JSON به‌عنوان Artifact ذخیره می‌شود. Telegram عمداً در این Workflow خاموش است تا در تست اولیه ارسال ناخواسته انجام نشود.


برای تست Core بدون اتصال واقعی:

```bash
python -m pytest -q
```

## اتصال Eways

```env
EWAYS_USERNAME=...
EWAYS_PASSWORD=...
SELECTED_IDS_STRING=...
```

اگر لاگین با Cookie لازم است:

```env
EWAYS_COOKIE=...
```

## اتصال Hamrahtel

نیازی به credential در Adapter فعلی ندارد؛ Source از URLهای تعریف‌شده در scraper قبلی استفاده می‌کند.

## Telegram

برای جلوگیری از ارسال ناخواسته، پیش‌فرض خاموش است:

```env
TELEGRAM_ENABLED=true
TELEGRAM_BOT_TOKEN=...
TELEGRAM_CHAT_ID=...
DRY_RUN=false
```

## نکته Production

قبل از Production، ابتدا با `DRY_RUN=true` و فقط JSON خروجی اجرا شود. پس از بررسی Matching، Telegram فعال شود.

## توسعه Source جدید

فقط یک Adapter جدید در `sources/` ایجاد کنید که `Source.fetch()` را پیاده‌سازی کند و `SourceProduct` برگرداند. Core به Source وابسته نیست.
