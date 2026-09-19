# افزودن یک منبع جدید

هسته‌ی برنامه (`core`) هرگز برای منبع جدید تغییر نمی‌کند. سه سطح دارید، از ساده به پیچیده:

## ۱) منبع بدون کد (JSON / HTML / CSV)
فقط یک بلوک به `config/sources.yaml` اضافه کنید. `currency_unit` **اجباری** است و واحد *خام* سایت را می‌گوید
(`toman` یا `rial`)؛ تبدیل فقط یک‌بار و در pipeline انجام می‌شود.

```yaml
- name: my_shop
  type: json                       # json | html | csv
  currency_unit: toman
  priority: 40                     # عدد کمتر = برنده‌ی تساوی قیمت
  min_expected_products: 30        # کمتر از این → منبع «مشکوک» و کنار گذاشته می‌شود
  url: https://api.my-shop.example/v1/products?category=mobile
  auth: {type: header, name: Authorization, env: MY_SHOP_TOKEN}   # راز فقط از env
  rate_limit_per_sec: 1
  retries: 3
  items_path: data.items
  fields: {id: id, title: name, price: price.amount, stock: inStock, url: link, color: color}
```
- HTML: `item_selector`, `fields: {title: ".t", price: ".price", url: ".t::attr(href)", id: "@attr(data-id)"}`, `out_of_stock_selector`.
- CSV: `columns: {title: ..., price: ..., stock: ..., url: ...}`.
- جستجوی هر محصول Watchlist: `search_url: "https://shop.example/search?q={query}"`.
- ترتیب انتخاب روش: API رسمی/JSON > HTML ساده > مرورگر (Playwright، فقط اگر ضروری).

## ۲) منبع با کد اختصاصی
`pricecompare/sources/_template.py` را کپی کنید، `records()` را بنویسید (لیستی از dict با کلیدهای
`id, title, price, stock, url, image, color, storage, ram, brand, extra`) و ثبت کنید:
```yaml
- name: my_shop
  class: pricecompare.sources.my_shop:MyShopSource
  currency_unit: rial
```
برای درخواست‌ها از `self.http.get(url)` استفاده کنید (rate-limit، retry، کش و احراز هویت آماده است).

## ۳) چک‌لیست قبل از فعال‌سازی
1. `python -m pricecompare check-sources` — تعداد محصولات و خطاها.
2. `python -m pricecompare run --dry-run` و بررسی `match-report` برای رد/تطبیق درست.
3. قیمت چند محصول را با سایت مقایسه کنید (خصوصاً واحد ریال/تومان). هشدار «خطای واحد» یعنی `currency_unit` غلط است.
4. یک snapshot از پاسخ سایت در `fixtures/` بگذارید و تست قرارداد بنویسید (بدون شبکه).
5. شرایط استفاده و robots.txt سایت را رعایت کنید.
