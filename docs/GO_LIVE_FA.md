# راه‌اندازی روی منابع واقعی (Eways + Hamrahtel)

پروفایل آماده: `config.real/` — منبع‌های `eways` (ریال) و `hamrahtel` (تومان) داخلش تعریف شده‌اند.

## ۱) نصب (یک‌بار)
```bash
pip install -r requirements.txt -r requirements-sources.txt
playwright install chromium
```

## ۲) اطلاعات ورود Eways
فایل `.env` کنار پروژه بسازید (از `.env.example` کپی کنید؛ در git نمی‌رود):
```
EWAYS_USERNAME=شماره‌موبایل-یا-یوزرنیم
EWAYS_PASSWORD=پسورد
```
Hamrahtel ورود نمی‌خواهد.

## ۳) محصولات دلخواه
`config.real/watchlist.yaml` را ویرایش کنید (برند، مدل دقیق مثل `iPhone 17 Pro`، ظرفیت، رم، ریجن اگر مهم است).

## ۴) بررسی سلامت منابع
```bash
python -m pricecompare --config-dir config.real check-sources
```
انتظار: هر دو `ok` و تعداد محصولات ≥ ۲۰. Hamrahtel با مرورگر کار می‌کند و چند دقیقه طول می‌کشد.

## ۵) اجرای آزمایشی (چیزی نوشته نمی‌شود)
```bash
python -m pricecompare --config-dir config.real run --dry-run
```
سپس اجرای واقعی و بازبینی:
```bash
python -m pricecompare --config-dir config.real run
python -m pricecompare --config-dir config.real match-report --status REVIEW   # تطبیق‌های نامطمئن
python -m pricecompare --config-dir config.real explain iphone17-256           # چرا این قیمت انتخاب شد
```
خروجی‌ها در `data/real/out/` هستند (`report.md` برای خواندن، `output.json` برای برنامه).

## ۶) کنترل‌های حتماً لازم قبل از اعتماد به عدد‌ها
1. **واحد Eways:** قیمت ۲–۳ محصول را با پنل Eways مقایسه کنید. در `output.json` باید `price_raw` (ریال) ده برابر `price_toman` باشد. اگر برعکس بود، `currency_unit: toman` بگذارید.
2. اگر هشدار «احتمال خطای واحد ریال/تومان» آمد، همین مورد است.
3. قیمت یک محصول را با سایت Hamrahtel مقایسه کنید.
4. در `match-report --status NO_MATCH` ببینید چیز درستی رد نشده باشد؛ اصلاح دستی در `config.real/overrides.yaml`.

## ۷) اجرای زمان‌بندی‌شده (GitHub Actions)
- در Settings → Secrets: `EWAYS_USERNAME` و `EWAYS_PASSWORD`.
- workflow آماده است؛ مرحله‌ی «real» را وقتی مطمئن شدید از `--dry-run` درآورید.
- ممکن است Eways به IP سرورهای GitHub سخت‌گیری کند؛ در آن صورت روی سیستم/سرور خودتان اجرا کنید (کد قدیمی از `EWAYS_PROXY` هم پشتیبانی می‌کرد).

## ۸) تلگرام (اختیاری)
در `config.real/settings.yaml`: `telegram_enabled: true` و `telegram_dry_run: false`، و در `.env`: `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID`.

## نکات
- Eways پنل عمده‌فروشی با ورود است؛ از حساب خودتان و مطابق شرایط استفاده‌ی آن استفاده کنید. فاصله‌ی اجراها را کم نکنید (پیش‌فرض workflow: هر ۳ ساعت).
- جزئیات محصول (رنگ/رم/ظرفیت دقیق) فقط برای محصولات هم‌خوان با watchlist خوانده می‌شود (`details: candidates`)، نه کل کاتالوگ.
- اگر Hamrahtel صفر محصول برگرداند، منبع «شکست‌خورده» حساب می‌شود و خروجی قبلی حفظ می‌شود.
