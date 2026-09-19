import logging
import re
import time
from dataclasses import dataclass
from typing import List, Tuple
from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeout

log = logging.getLogger('scraper')

CATEGORIES = {
    'mobile': 'https://hamrahtel.com/quick-checkout?category=mobile',
    'laptop': 'https://hamrahtel.com/quick-checkout?category=laptop',
    'tablet': 'https://hamrahtel.com/quick-checkout?category=tablet',
    'console': 'https://hamrahtel.com/quick-checkout?category=game-console',
}

NOISE = {
    'تومانءء', 'تومان', 'نامشخص', 'جستجو در مدل‌ها', 'کامپیوتر', 'دوربین تحت شبکه',
    'موتور برق', 'اندروید باکس', 'بیمه', 'ماشین های اداری', 'لوازم جانبی موبایل', 'تگ هوشمند'
}
VALID_BRANDS = [
    'Galaxy', 'POCO', 'Redmi', 'iPhone', 'Redtone', 'VOCAL', 'TCL', 'NOKIA',
    'Honor', 'Huawei', 'GLX', '+Otel', 'اینچی'
]

@dataclass(frozen=True)
class Product:
    brand: str
    model: str
    price: str
    color: str = ''


PERSIAN_DIGITS = str.maketrans('۰۱۲۳۴۵۶۷۸۹', '0123456789')
COLOR_ALIASES = {
    'مشکی': 'مشکی', 'سیاه': 'مشکی', 'black': 'مشکی',
    'سفید': 'سفید', 'white': 'سفید',
    'خاکستری': 'خاکستری', 'طوسی': 'خاکستری', 'gray': 'خاکستری', 'grey': 'خاکستری',
    'آبی': 'آبی', 'آبی روشن': 'آبی روشن', 'آبی تیره': 'آبی تیره', 'blue': 'آبی',
    'سبز': 'سبز', 'green': 'سبز', 'قرمز': 'قرمز', 'red': 'قرمز',
    'بنفش': 'بنفش', 'purple': 'بنفش', 'صورتی': 'صورتی', 'pink': 'صورتی',
    'طلایی': 'طلایی', 'gold': 'طلایی', 'نقره ای': 'نقره ای', 'نقره‌ای': 'نقره ای', 'silver': 'نقره ای',
}

def normalize_digits(text: str) -> str:
    return str(text or '').translate(PERSIAN_DIGITS)

def detect_color(text: str) -> str:
    s = clean_text(text).lower()
    for raw, canonical in sorted(COLOR_ALIASES.items(), key=lambda x: len(x[0]), reverse=True):
        if raw.lower() in s:
            return canonical
    return ''

def clean_text(text: str) -> str:
    text = normalize_digits(text).replace('\xa0', ' ').strip()
    for item in NOISE:
        text = text.replace(item, ' ')
    # Hamrahtel occasionally returns invisible/Arabic letter-mark artifacts
    # after the price (e.g. `تومانءء`). They are not part of the price and
    # must never leak into the parsed product value.
    text = text.replace('تومان', ' ')
    text = re.sub(r'[ءٕٖٜٟٔٗ٘ٙٚٛٝٞ]', ' ', text)
    return re.sub(r'\s+', ' ', text).strip(' -|')


def is_price(text: str) -> bool:
    text_n = normalize_digits(text)
    # Product titles contain Latin model/spec words (GB, RAM, etc.), while a
    # price line is numeric plus optional currency text.
    if re.search(r'[A-Za-z]', text_n):
        return False
    digits = re.sub(r'[^0-9]', '', text_n)
    # Product titles often contain several short numeric specs (e.g. 17/128/4).
    # A price must have at least six digits after normalization.
    return len(digits) >= 6


def parse_card_variants(lines: List[str]) -> List[Product]:
    """Parse one Hamrahtel card into one Product per color/price variant.

    Hamrahtel can render a single model once and then list several colors,
    each immediately followed by its own price. The old parser selected only
    the first price and consequently lost the color variants.
    """
    lines = [clean_text(x) for x in lines if clean_text(x)]
    if not lines:
        return []

    price_indexes = [i for i, x in enumerate(lines) if is_price(x)]
    if not price_indexes:
        return []

    # Find the base product title: first meaningful non-price/non-color line.
    title = ''
    for x in lines:
        if is_price(x) or x == 'مشخصات کالا' or x.startswith('برند') or detect_color(x):
            continue
        title = x
        break
    if not title:
        # Fallback to the first non-price line, even if it contains a color.
        title = next((x for x in lines if not is_price(x)), '')
    if not title:
        return []

    parts = title.split()
    brand = parts[0] if parts else ''
    if brand not in VALID_BRANDS:
        brand = ''
    model = title if not brand else ' '.join(parts[1:])

    products: List[Product] = []
    for price_index in price_indexes:
        color = ''
        # The color is normally the nearest preceding color-labelled line.
        for j in range(price_index - 1, -1, -1):
            candidate = detect_color(lines[j])
            if candidate:
                color = candidate
                break
            if is_price(lines[j]):
                break
        products.append(Product(brand, model, lines[price_index], color))
    return products


def parse_card_text(lines: List[str]) -> Product | None:
    """Backward-compatible single-product parser; returns the first variant."""
    variants = parse_card_variants(lines)
    return variants[0] if variants else None


def extract_card_candidates(page) -> List[Product]:
    selectors = [
        '[data-testid*="product"]', '[data-testid*="Product"]',
        '[class*="product-card"]', '[class*="ProductCard"]',
        '[class*="productCard"]', '[class*="product-item"]',
    ]
    seen = set()
    products = []
    for selector in selectors:
        try:
            cards = page.locator(selector)
            count = min(cards.count(), 3000)
            for i in range(count):
                text = cards.nth(i).inner_text(timeout=3000)
                for product in parse_card_variants(text.splitlines()):
                    if product and product.price:
                        key = (product.brand, product.model, product.price, product.color)
                        if key not in seen:
                            seen.add(key)
                            products.append(product)
        except Exception:
            continue
    return products


def _product_from_payload(item) -> Product | None:
    if not isinstance(item, dict):
        return None
    name = item.get('name') or item.get('title') or item.get('product_name') or item.get('productName') or item.get('model')
    price = item.get('price') or item.get('sale_price') or item.get('salePrice') or item.get('final_price') or item.get('finalPrice')
    if name is None or price is None:
        return None
    name = clean_text(str(name))
    price_text = clean_text(str(price))
    if not name or not is_price(price_text):
        return None
    color = detect_color(str(item.get('color') or item.get('colour') or '')) or detect_color(name)
    parts = name.split()
    brand = parts[0] if parts and parts[0] in VALID_BRANDS else ''
    model = ' '.join(parts[1:]) if brand else name
    return Product(brand, model, price_text, color)


def _walk_payload(value, out):
    if isinstance(value, dict):
        product = _product_from_payload(value)
        if product:
            out.append(product)
        for child in value.values():
            _walk_payload(child, out)
    elif isinstance(value, list):
        for child in value:
            _walk_payload(child, out)


def extract_network_products(responses) -> List[Product]:
    """Extract product records from JSON/XHR responses when the DOM is empty."""
    products = []
    for response in responses:
        try:
            content_type = (response.headers.get('content-type') or '').lower()
            if 'json' not in content_type:
                continue
            payload = response.json()
            _walk_payload(payload, products)
        except Exception:
            continue
    return dedupe_products(products)


def _is_color_label(x: str) -> bool:
    """A short standalone colour label such as 'مشکی' or 'آبی روشن' (NOT a title that merely mentions a colour)."""
    return bool(detect_color(x)) and not re.search(r'[A-Za-z]', x) and len(x.split()) <= 3


def _split_title(title: str):
    parts = title.split()
    brand = parts[0] if parts else ''
    if brand not in VALID_BRANDS:
        brand = ''
    return brand, (title if not brand else ' '.join(parts[1:]))


def parse_body_lines(raw_lines: List[str]) -> List[Product]:
    """Pair every price line with its OWN title.

    pricecompare fix: the original implementation cut a fixed window around each price and assigned ALL prices in
    that window to the FIRST title of the window, so prices of the previous card were attached to the next card's
    title (e.g. the RAM-6GB price shown under the RAM-4GB title). Here, for each price line we walk backwards:
    prices/colour labels of the same card are skipped, the nearest colour label (before crossing another price) is
    the variant colour, and the first remaining line is the card title.
    """
    products = []
    for i, line in enumerate(raw_lines):
        if not is_price(line):
            continue
        color, crossed_price, title = '', False, ''
        for j in range(i - 1, max(-1, i - 13), -1):
            x = raw_lines[j]
            if is_price(x):
                crossed_price = True
                continue
            if _is_color_label(x):
                if not color and not crossed_price:
                    color = detect_color(x)
                continue
            if x == 'مشخصات کالا' or x.startswith('برند'):
                continue
            title = x
            break
        if not title:
            continue
        brand, model = _split_title(title)
        products.append(Product(brand, model, line, color))
    return dedupe_products(products)


def extract_body_text_fallback(page) -> List[Product]:
    """Last-resort parser for Hamrahtel DOM changes (renders body text, pairs prices with titles)."""
    try:
        # IMPORTANT: do not call clean_text() on the complete body before splitlines(): it collapses whitespace.
        body = page.locator("body").inner_text(timeout=10000)
    except Exception:
        return []
    if not body:
        return []
    raw_lines = [c for c in (clean_text(x) for x in body.splitlines()) if c]
    return parse_body_lines(raw_lines)


def extract_legacy(page, skip_items: int) -> List[Product]:
    # Kept as a compatibility fallback for the current site's existing DOM.
    page.wait_for_selector('[class*="mantine-Text"]', timeout=60000)
    elements = page.locator('[class*="mantine-Text"]')
    raw = []
    for i in range(elements.count()):
        try:
            value = clean_text(elements.nth(i).inner_text())
            if value:
                raw.append(value)
        except Exception:
            pass
    raw = raw[skip_items:]
    products = []
    # The current project historically treats each text element as a product-like row.
    # Preserve that behavior but normalize it and only keep rows that contain a price.
    for item in raw:
        parts = item.split()
        price_pos = next((i for i, p in enumerate(parts) if is_price(p)), None)
        if price_pos is None:
            continue
        price = parts[price_pos]
        name_parts = parts[:price_pos] + parts[price_pos + 1:]
        if not name_parts:
            continue
        name = ' '.join(name_parts)
        brand = name.split()[0] if name.split() else ''
        if brand not in VALID_BRANDS:
            brand = ''
        model = name if not brand else ' '.join(name.split()[1:])
        products.append(Product(brand, model, price))
    return products


def scroll_page(page, max_scrolls: int):
    stable = 0
    previous = -1
    for _ in range(max_scrolls):
        height = page.evaluate('document.body.scrollHeight')
        page.evaluate('window.scrollTo(0, document.body.scrollHeight)')
        time.sleep(1.2)
        new_height = page.evaluate('document.body.scrollHeight')
        if new_height == previous or new_height == height:
            stable += 1
            if stable >= 2:
                break
        else:
            stable = 0
        previous = new_height


def scrape_category(page, url: str, attempts: int, timeout_ms: int, max_scrolls: int, skip_items: int) -> Tuple[List[Product], bool]:
    for attempt in range(1, attempts + 1):
        try:
            log.info('Scrape %s attempt %s/%s', url, attempt, attempts)
            network_responses = []

            def _capture_response(response):
                try:
                    if response.request.resource_type in {'xhr', 'fetch'}:
                        network_responses.append(response)
                except Exception:
                    pass

            page.on('response', _capture_response)
            try:
                page.goto(url, wait_until='domcontentloaded', timeout=timeout_ms)

                # Give React/Mantine time to render the initial catalogue. Do not
                # use networkidle: analytics and long-lived connections can keep
                # that state open indefinitely in CI.
                try:
                    page.wait_for_timeout(2500)
                except Exception:
                    time.sleep(2.5)

                product_selector = ', '.join([
                    '[data-testid*="product"]',
                    '[data-testid*="Product"]',
                    '[class*="product-card"]',
                    '[class*="ProductCard"]',
                    '[class*="productCard"]',
                    '[class*="product-item"]',
                    '[class*="mantine-Text"]',
                ])
                try:
                    page.wait_for_selector(
                        product_selector,
                        state='attached',
                        timeout=min(15000, timeout_ms),
                    )
                except PlaywrightTimeout:
                    log.warning('No known product DOM appeared on %s; continuing with fallback extraction', url)

                # Lazy-loaded products are requested while scrolling. Keep the
                # response listener active until after scrolling so XHR/Fetch JSON
                # can also be used as a reliable extraction source.
                scroll_page(page, max_scrolls)
                try:
                    page.wait_for_timeout(1500)
                except Exception:
                    time.sleep(1.5)

                # IMPORTANT: do not stop at the first non-empty extractor. A
                # generic selector can return one card while the real catalogue
                # is present in the rendered body/network payload. Merge every
                # available extraction path and deduplicate at the end.
                candidates = []
                card_products = extract_card_candidates(page)
                if card_products:
                    log.info('Hamrahtel card extractor: %s', len(card_products))
                    candidates.extend(card_products)

                try:
                    legacy_products = extract_legacy(page, 0)
                    if legacy_products:
                        log.info('Hamrahtel text extractor: %s', len(legacy_products))
                        candidates.extend(legacy_products)
                except Exception as exc:
                    log.debug('Hamrahtel legacy text extractor unavailable: %s', exc)

                network_products = extract_network_products(network_responses)
                if network_products:
                    log.info('Hamrahtel network extractor: %s', len(network_products))
                    candidates.extend(network_products)

                body_products = extract_body_text_fallback(page)
                if body_products:
                    log.info('Hamrahtel body fallback: %s', len(body_products))
                    candidates.extend(body_products)

                products = dedupe_products(candidates)
                log.info('Extracted %s products from %s', len(products), url)
                if products:
                    return products, True
            finally:
                try:
                    page.remove_listener('response', _capture_response)
                except Exception:
                    pass
        except PlaywrightTimeout as exc:
            log.warning('Timeout on %s: %s', url, exc)
        except Exception as exc:
            log.warning('Scrape error on %s: %s', url, exc)
        time.sleep(min(5 * attempt, 15))
    return [], False

def dedupe_products(products: List[Product]) -> List[Product]:
    seen = set()
    result = []
    for p in products:
        key = (p.brand.strip().lower(), p.model.strip().lower(), p.price.strip(), p.color.strip().lower())
        if key in seen:
            continue
        seen.add(key)
        result.append(p)
    return result


def fetch_all_products(settings) -> Tuple[List[Product], bool]:
    all_products = []
    category_success = True
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True, args=['--no-sandbox', '--disable-dev-shm-usage', '--disable-gpu'])
        context = browser.new_context(
            user_agent='Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120.0.0.0 Safari/537.36',
            viewport={'width': 1920, 'height': 1080}, locale='fa-IR',
            extra_http_headers={'Accept-Language': 'fa-IR,fa;q=0.9,en-US;q=0.8'}
        )
        page = context.new_page()
        page.set_default_timeout(settings.page_timeout_ms)
        try:
            for category, url in CATEGORIES.items():
                products, ok = scrape_category(page, url, settings.scrape_attempts, settings.page_timeout_ms, settings.max_scrolls, settings.legacy_skip_items)
                if not ok:
                    category_success = False
                    log.error('Category %s failed after retries', category)
                    continue
                all_products.extend(products)
        finally:
            context.close()
            browser.close()
    return dedupe_products(all_products), category_success
