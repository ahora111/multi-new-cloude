"""`debug-page <url>`: show what a shop page REALLY contains, so a new source can be written from facts, not guesses.

Prints: rendered text around the first prices, JSON/GraphQL responses that mention prices, schema.org JSON-LD,
Next.js/Nuxt state, the HTML of the first product-card candidates, product-looking links and pagination hints.
No secrets are printed (cookies/headers are never dumped)."""
from __future__ import annotations
import json
import re

PRICE_RE = re.compile(r"(?<![\d.,٬])(?:\d{1,3}(?:[,٬.]\d{3}){1,3}|\d{5,})(?![\d])")
_FA = str.maketrans("۰۱۲۳۴۵۶۷۸۹٠١٢٣٤٥٦٧٨٩", "01234567890123456789")

CARD_JS = """
() => {
  const priceRe = /(\\d{1,3}([,٬.]\\d{3}){1,3})/;
  const out = [], seen = new Set();
  for (const a of document.querySelectorAll('a[href]')) {
    let el = a, best = null;
    for (let i = 0; i < 6 && el; i++, el = el.parentElement) {
      const t = (el.innerText || '').replace(/[۰-۹]/g, d => '۰۱۲۳۴۵۶۷۸۹'.indexOf(d));
      const n = (t.match(/(\\d{1,3}([,٬.]\\d{3}){1,3})/g) || []).length;
      if (n >= 1 && n <= 3 && t.length < 600) best = el;
      else if (n > 3) break;
    }
    if (best && !seen.has(best)) { seen.add(best); out.push(best.outerHTML.slice(0, 1800)); }
    if (out.length >= 3) break;
  }
  return out;
}
"""


def norm_line(x: str) -> str:
    return re.sub(r"\s+", " ", (x or "").translate(_FA)).strip()


def is_price_line(x: str) -> bool:
    return bool(PRICE_RE.fullmatch(norm_line(x).replace(" تومان", "").replace(" ریال", "").strip()))


def numbered(lines, first, n=80, context=12):
    a = max(0, first - context)
    return [f"{i:4d} | {x}" for i, x in enumerate(lines[a:a + n], start=a)]


def dump(url, lines=80, grep="", timeout_ms=90000, max_scrolls=15, show_html=True) -> str:
    from playwright.sync_api import sync_playwright
    out, json_hits = [], []
    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True)
        page = browser.new_page()

        def on_response(resp):
            try:
                ct = resp.headers.get("content-type") or ""
                if "json" in ct:
                    body = resp.text()
                    if re.search(r"price|قیمت|amount", body, re.I):
                        json_hits.append((body.lower().count("price"), len(body), resp.request.method, resp.url[:150], body))
            except Exception:
                pass
        page.on("response", on_response)
        page.goto(url, wait_until="domcontentloaded", timeout=timeout_ms)
        page.wait_for_timeout(5000)
        for _ in range(max_scrolls):
            page.mouse.wheel(0, 4000)
            page.wait_for_timeout(700)
        body = page.locator("body").inner_text(timeout=15000)
        html = page.content()
        cards = page.evaluate(CARD_JS) if show_html else []
        hrefs = page.eval_on_selector_all("a[href]", "els => els.map(e => [e.href, (e.innerText||'').trim().slice(0,60)])")
        title = page.title()
        browser.close()
    raw = [c for c in (norm_line(x) for x in body.splitlines()) if c]
    prices = [i for i, x in enumerate(raw) if PRICE_RE.search(x)]
    out.append(f"URL: {url} | title: {title}")
    out.append(f"text lines: {len(raw)} | lines with a price-like number: {len(prices)}")
    out.append("markers: " + ", ".join(k for k, v in {
        "__NEXT_DATA__": "__NEXT_DATA__" in html, "__NUXT__": "__NUXT__" in html, "JSON-LD": "application/ld+json" in html,
        "woocommerce": "woocommerce" in html.lower(), "shopify": "shopify" in html.lower(), "graphql": "graphql" in html.lower(),
        "next-page-link": bool(re.search(r"[?&]page=\d", html)), "load-more-button": bool(re.search(r"بیشتر|load more", html, re.I)),
    }.items() if v) or "none")
    ld = re.findall(r'<script[^>]*application/ld\+json[^>]*>(.*?)</script>', html, re.S)
    if ld:
        out.append(f"JSON-LD blocks: {len(ld)}; first 800 chars: {ld[0].strip()[:800]}")
    out.append("JSON responses mentioning price (count, bytes, method, url): " +
               str([(a, b, c, d) for a, b, c, d, _ in sorted(json_hits, reverse=True)[:6]]))
    prod_links = [f"{h} | {t}" for h, t in dict.fromkeys(map(tuple, hrefs)) if re.search(r"product|/p/|/dkp|/item|/goods", h, re.I)][:10]
    out.append("product-looking links: " + (str(prod_links) if prod_links else "none"))
    pag = [f"{h} | {t}" for h, t in dict.fromkeys(map(tuple, hrefs)) if re.search(r"[?&]page=|/page/\d", h)][:6]
    out.append("pagination links: " + (str(pag) if pag else "none"))
    if grep:
        out.append(f"--- lines matching {grep!r} (3 before / 6 after) ---")
        for i in [i for i, x in enumerate(raw) if grep.lower() in x.lower()][:6]:
            out += [f"{j:4d} | {raw[j]}" for j in range(max(0, i - 3), min(len(raw), i + 7))] + ["  ..."]
    out.append("--- rendered text around the first price ---")
    out += numbered(raw, prices[0] if prices else 0, lines)
    if json_hits:
        big = max(json_hits, key=lambda h: h[1])
        out.append(f"--- largest JSON with prices ({big[1]} bytes) {big[2]} {big[3]} ---")
        out.append(big[4][:2500])
    for i, c in enumerate(cards, 1):
        out.append(f"--- product-card candidate {i} (HTML) ---")
        out.append(c)
    return "\n".join(out)
