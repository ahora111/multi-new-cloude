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

## Farnaa source

The project now includes a `farnaa` source for the mobile catalog at `https://farnaa.com/category/mobile`.

- Production config: `config.real/sources.yaml`
- Default config: `config/sources.yaml`
- Parser: `pricecompare/sources/farnaa.py`
- Offline fixture: `fixtures/farnaa_mobile.html`
- Tests: `tests/test_farnaa.py`

The parser uses Farnaa's embedded `window.productAnalyticsData` as the structured catalog source and enriches records from rendered product cards with product URL/image/color. Farnaa declares prices in toman. Product and variant IDs are kept stable and price is never part of the ID.

Run only Farnaa:

```bash
python -m pricecompare --config-dir config.real run --dry-run --only-source farnaa
```

Run the Farnaa parser tests:

```bash
pytest -q tests/test_farnaa.py
```


## KasraPars source

The project includes a `kasrapars` source for the wholesale catalog at `https://plus.kasrapars.ir/`.

- **Since Mehr 1404 the site is a Nuxt/Vue SPA: its HTML contains no product cards at all.** The source therefore reads the site's own public web API (`api.kasrapars.ir/api/web/v10/product/index-brand`) and follows `_links.next` for pagination. The old HTML parser is kept as a fallback (fixtures / other site versions).
- API prices are **RIAL** (the site divides by 10 for display) — `config.real/sources.yaml` therefore declares `currency_unit: rial` for kasrapars; the rial→toman conversion happens in the pipeline only.
- Each colour/variety becomes a separate `Offer` keyed by the API variety id; Persian colour names are canonicalised by the central dictionary. Unavailable items are excluded server-side via `status_available=1`.
- If the API is ever blocked, `browser_fallback: true` re-reads the same API responses from inside a real Chromium session.

Run only KasraPars:

```bash
python -m pricecompare --config-dir config.real run --dry-run --only-source kasrapars
```

Run the KasraPars parser tests:

```bash
pytest -q tests/test_kasrapars.py
```


## Digikala B2B source

The project includes a `digikala_b2b` source for the wholesale portal at `https://b2b.digikala.com/` (category 3 = mobile phones, sorted `price-desc` like the site UI).

- **b2b.digikala.com is a Next.js SPA: the HTML shell contains no product data.** The source reads the portal's own public JSON API (no login needed): listing `GET /api/v1/products?category_id=3&page=1&sort=price-desc` with Laravel-style pagination (`meta`/`links.next`, ~12 products/page, 60+ pages) and product details `GET /api/v1/products/pdp/{id}`.
- API prices are **RIAL** (PDP `formatted_price` is "﷼5,199,990,000") — `config.real/sources.yaml` declares `currency_unit: rial`; the rial→toman conversion happens in the pipeline only.
- **Sold-out products are listed with `price == 0` and an empty `colors` array** (their PDP has `in_stock: false` and no variants). By default these rows are dropped (`include_out_of_stock: false`), matching the other sources' site-side availability filters; set the option to `true` to keep them as non-competing "نا موجود" rows.
- `details: all` (default) fetches the PDP payload for every in-stock listing row and emits **one offer per variant** with the exact per-colour price, Persian colour name, warranty and stock (`remaining_stock` 0 = sold out, null = no explicit limit). `details: candidates` refines only watchlist candidates (like Eways); `details: none` keeps the raw listing rows (colour unknown for multi-colour products).
- Product links use the SPA route `https://b2b.digikala.com/products/product/{id}`; images come from `dkstatics-public.digikala.com`.
- Persian colour names (آبی تیره, سرمه ای, …) are canonicalised by the central dictionary — `آبی تیره/سرمه ای/navy/dark blue` all map to `deep_blue`, the colour name KasraPars uses, so the same phone from different shops competes in ONE variant row.
- The B2B catalog holds ~740 listed phones of which only ~70–90 are in stock at any time; a full crawl is ~62 listing pages + ~80 PDP calls (a couple of minutes at `rate_limit_per_sec: 2`).

Run only Digikala B2B:

```bash
python -m pricecompare --config-dir config.real run --dry-run --only-source digikala_b2b
```

Run the Digikala B2B parser tests:

```bash
pytest -q tests/test_digikala_b2b.py
```
