# pricecompare — مقایسه‌ی قیمت چندمنبعی

فهرست محصولات دلخواه (`config/watchlist.yaml`) را از چند منبع می‌خواند، مدل/ظرفیت/رم/رنگ/ریجن را **دقیق** تطبیق می‌دهد
و برای هر رنگ کمترین قیمت **معتبر** را انتخاب می‌کند.

## اجرا
```bash
pip install -r requirements.txt
python -m pricecompare run                 # خروجی در data/out/
python -m pricecompare run --dry-run       # بدون نوشتن فایل
python -m pricecompare check-sources       # سلامت منابع
python -m pricecompare match-report --status NO_MATCH   # چرا چیزی تطبیق نخورد؟
python -m pricecompare explain iphone17-256             # توضیح انتخاب قیمت
python -m pytest -q                        # تست‌ها (بدون شبکه)
```
نمونه‌ی آماده با داده‌های `fixtures/` اجرا می‌شود. برای سایت واقعی، بلوک‌های `config/sources.yaml` را با `url`/`auth` واقعی جایگزین کنید
(`docs/ADD_SOURCE.md`).

## منابع واقعی (Eways و Hamrahtel)
پروفایل آماده در `config.real/` و راهنمای قدم‌به‌قدم در `docs/GO_LIVE_FA.md`.
```bash
pip install -r requirements.txt -r requirements-sources.txt && playwright install chromium
python -m pricecompare --config-dir config.real check-sources
```

## خروجی‌ها (`data/out/`)
| فایل | کاربرد |
|---|---|
| `output.json` | schema نسخه‌دار: محصول → واریانت (رنگ) → همه‌ی offers + `winner` + `runner_up` + `savings` + `why` + `warnings` |
| `report.csv` | یک ردیف برای هر واریانت (اکسل) |
| `report.md` | گزارش فارسی قابل خواندن |
| `run_summary.json` | وضعیت هر منبع، تعدادها، هشدارها |
| `matching_report.json` | دلیل تطبیق/ردِ تک‌تک پیشنهادها |

## قواعد مهم
- **تطبیق:** اول شرط‌های سخت (برند، رده‌ی Pro/Max/Ultra/Air/FE/…، شماره‌ی مدل، ظرفیت، رم، ریجن، 4G/5G، اکتیو/نان‌اکتیو)، بعد شباهت متنی. مشخصه‌ی ناموجود که watchlist لازم دارد → `REVIEW` (وارد قیمت‌گذاری نمی‌شود، مگر `review_as_match: true`).
- **قیمت:** فقط موجود، تازه و معتبر. قیمت پرت دوطرفه (≥۳ پیشنهاد) حذف می‌شود؛ با ۱–۲ پیشنهاد و اختلاف زیاد همه `needs_review` می‌شوند. اگر میانه‌ی نسبت قیمت دو منبع ≈ ۱۰ باشد هشدار خطای واحد ریال/تومان می‌دهد.
- **پایداری:** شکست یک منبع بقیه را نمی‌شکند؛ اگر همه شکست بخورند خروجی قبلی دست‌نخورده می‌ماند و کد خروج ۲ است. `--require-all-sources` → کد ۳. lock از اجرای همزمان جلوگیری می‌کند.
- **تنظیمات:** کلید ناشناخته در `settings.yaml` خطا است، پس تنظیم بی‌اثر وجود ندارد.

کدهای خروج: 0 موفق | 2 همه منابع شکست | 3 نقض `--require-all-sources` | 4 خطای تنظیمات | 5 اجرای همزمان | 6 ارسال تلگرام ناموفق (داده ذخیره شده است).

## محدودیت‌ها (صادقانه)
- حالت `discovery` (کشف کل کاتالوگ) پیاده‌سازی نشده است.
- افزونه‌های Eways/Hamrahtel با تست‌های ساختگی (fake) بررسی شده‌اند؛ روی سایت واقعی اجرا نشده‌اند (`pytest -m live` را روی سیستم خودتان بزنید).
- اگر watchlist شبکه‌ی 4G/5G را مشخص نکند، هر دو پذیرفته می‌شوند (در مدل بنویسید: `Galaxy A17 4G`).
- ریجن/اکتیو در watchlist مشخص نشده باشد و پیشنهادها ریجن‌های مختلف داشته باشند، واریانت `needs_review` می‌شود.
