"""Hamrahtel quick-checkout source (Playwright). Wraps the original scraper in sources/vendor/.

sources.yaml:
  - name: hamrahtel
    type: hamrahtel
    currency_unit: toman
    min_expected_products: 20      # the original project used 20 as the anomaly threshold
    categories: [mobile]           # mobile | laptop | tablet | console
    page_timeout_ms: 90000
    scrape_attempts: 3
    max_scrolls: 20
    legacy_skip_items: 25
Requires:  pip install playwright && playwright install chromium
"""
from __future__ import annotations
import importlib
import json
from types import SimpleNamespace
from .base import Source
from ..extract import Extractor


def _scraper():
    try:
        return importlib.import_module("pricecompare.sources.vendor.hamrahtel_scraper")
    except ImportError as exc:                                        # pragma: no cover - env specific
        raise RuntimeError("Hamrahtel needs Playwright: pip install playwright && playwright install chromium") from exc


def _dig(obj, *path):
    for k in path:
        obj = obj.get(k) if isinstance(obj, dict) else None
    return obj


def nodes_from_json(payload) -> list:
    """All product nodes ({name, variants, ...}) found anywhere in a GraphQL response (Saleor-style edges/node)."""
    out = []

    def walk(o):
        if isinstance(o, dict):
            edges = o.get("edges")
            if isinstance(edges, list):
                for e in edges:
                    n = e.get("node") if isinstance(e, dict) else None
                    if isinstance(n, dict) and "name" in n and "variants" in n:
                        out.append(n)
            for v in o.values():
                walk(v)
        elif isinstance(o, list):
            for v in o:
                walk(v)
    walk(payload)
    return out


def _variant_color(variant) -> str:
    """Extract the colour from structured GraphQL attributes, with name fallback."""
    attrs = variant.get("attributes") if isinstance(variant, dict) else None
    if isinstance(attrs, list):
        for item in attrs:
            if not isinstance(item, dict):
                continue
            attr = item.get("attribute") or {}
            attr_name = str(attr.get("name") or "").strip().lower()
            attr_slug = str(attr.get("slug") or "").strip().lower()
            if attr_slug not in {"color", "colour"} and attr_name not in {"color", "colour", "رنگ"}:
                continue
            values = item.get("values") or []
            if isinstance(values, list):
                for value in values:
                    if isinstance(value, dict):
                        name = str(value.get("name") or value.get("value") or "").strip()
                    else:
                        name = str(value or "").strip()
                    if name:
                        return name
    return str(variant.get("name") or "").strip()


def records_from_nodes(nodes, link="", url_template="") -> list:
    """One record per product VARIANT (= colour). Numbers, colour, and real stock come straight from the API."""
    seen, recs = set(), []
    for n in nodes:
        title = str(n.get("name") or "").strip()
        if not title:
            continue
        slug = str(n.get("slug") or "")
        for v in n.get("variants") or []:
            vid = v.get("id") or f"{n.get('id')}:{v.get('name')}"
            if vid in seen:
                continue
            seen.add(vid)
            amount = _dig(v, "pricing", "price", "gross", "amount")
            if not amount:
                continue
            qty = v.get("quantityAvailable")
            available = (n.get("isAvailableForPurchase", True) is not False and n.get("isAvailable", True) is not False
                         and (qty is None or qty > 0))
            recs.append({"id": vid, "title": title, "price": amount, "stock": "in_stock" if available else "out_of_stock",
                         "url": url_template.format(slug=slug) if (url_template and slug) else link,
                         "color": _variant_color(v), "extra": {"quantity": qty, "slug": slug}})
    return recs


def browse_hamrahtel(url, timeout_ms=90000, max_scrolls=20, attempts=3):
    """One browser session: capture every GraphQL response with products AND the rendered page text."""
    scraper = _scraper()
    from playwright.sync_api import sync_playwright
    last = None
    for _ in range(max(1, attempts)):
        nodes = []
        try:
            with sync_playwright() as pw:
                browser = pw.chromium.launch(headless=True)
                page = browser.new_page()

                def on_response(resp):
                    try:
                        if "graphql" in resp.url and "json" in (resp.headers.get("content-type") or ""):
                            nodes.extend(nodes_from_json(json.loads(resp.text())))
                    except Exception:
                        pass
                page.on("response", on_response)
                page.goto(url, wait_until="domcontentloaded", timeout=timeout_ms)
                page.wait_for_timeout(5000)
                scraper.scroll_page(page, max_scrolls)
                page.wait_for_timeout(1500)
                body = page.locator("body").inner_text(timeout=15000)
                browser.close()
            lines = [c for c in (scraper.clean_text(x) for x in body.splitlines()) if c]
            if nodes or any(scraper.is_price(x) for x in lines):
                return nodes, lines
            last = RuntimeError("the page rendered no products")
        except Exception as exc:                                    # network / timeout / browser crash: retry
            last = exc
    raise RuntimeError(f"Hamrahtel browser session failed after {attempts} attempts: {last}")


class HamrahtelSource(Source):
    type_name = "hamrahtel"

    def _records_from_products(self, products, link):
        seen, out = {}, []
        for p in products:
            base = f"{p.brand}|{p.model}|{p.color}"
            seen[base] = seen.get(base, 0) + 1
            # stable id (does NOT contain the price, so history/overrides survive price changes)
            oid = base if seen[base] == 1 else f"{base}#{seen[base]}"
            out.append({"id": oid, "title": " ".join(x for x in (p.brand, p.model) if x), "price": p.price,
                        "stock": getattr(p, "stock", "in_stock"), "url": link, "color": p.color, "brand": p.brand})
        return out

    def records(self, watchlist):
        scraper = _scraper()
        wanted = self.o.get("categories") or ["mobile"]
        unknown = [c for c in wanted if c not in scraper.CATEGORIES]
        if unknown:
            raise ValueError(f"source {self.name}: unknown categories {unknown}; known: {sorted(scraper.CATEGORIES)}")
        strategy = self.o.get("strategy", "auto")
        if strategy not in ("auto", "graphql", "text", "legacy"):
            raise ValueError(f"source {self.name}: strategy must be auto|graphql|text|legacy")
        link = scraper.CATEGORIES[wanted[0]] if len(wanted) == 1 else ""

        if strategy == "legacy":                                     # the original scraper, kept for comparison
            original = scraper.CATEGORIES
            scraper.CATEGORIES = {k: v for k, v in original.items() if k in wanted}
            opts = SimpleNamespace(
                page_timeout_ms=int(self.o.get("page_timeout_ms", 90000)), scrape_attempts=int(self.o.get("scrape_attempts", 3)),
                max_scrolls=int(self.o.get("max_scrolls", 20)), legacy_skip_items=int(self.o.get("legacy_skip_items", 25)))
            try:
                products, ok = scraper.fetch_all_products(opts)
            finally:
                scraper.CATEGORIES = original
            if not products:
                raise RuntimeError("Hamrahtel returned zero products (site unreachable, blocked, or page layout changed)")
            if not ok:
                import logging
                logging.getLogger("pricecompare").warning("hamrahtel: at least one category failed after retries")
            recs, self.note = self._records_from_products(products, link), "strategy=legacy"
        else:
            if len(wanted) != 1:
                raise ValueError(f"source {self.name}: strategy {strategy!r} supports one category at a time")
            nodes, lines = browse_hamrahtel(link, int(self.o.get("page_timeout_ms", 90000)),
                                            int(self.o.get("max_scrolls", 20)), int(self.o.get("scrape_attempts", 3)))
            graph = records_from_nodes(nodes, link, self.o.get("product_url_template", ""))
            text = self._records_from_products(scraper.parse_body_lines(lines), link)
            if strategy == "graphql":
                recs, used = graph, "graphql"
            elif strategy == "text":
                recs, used = text, "text"
            else:                                                    # auto: prefer the API, but supplement missing variants from page text
                use_graph = bool(graph) and len(graph) >= 0.7 * len(text)
                if use_graph:
                    # The GraphQL catalog can occasionally omit a rendered variant even
                    # though the browser page contains it (for example iPhone 17
                    # "Sage Green"). Keep the API as the primary source, but recover
                    # text-only variants by canonical product/variant identity.
                    ex = Extractor(getattr(self.settings, "dictionaries_file", None))

                    def identity(row):
                        a = ex.parse(row.get("title", ""), row.get("brand", ""), row.get("color", ""),
                                     row.get("storage", ""), row.get("ram", ""))
                        return (a.brand, tuple(sorted(a.core)), tuple(a.tiers), a.storage_gb, a.ram_gb,
                                a.region, a.network, a.condition, a.color or "unknown")

                    graph_ids = {identity(r) for r in graph}
                    supplement = [r for r in text if identity(r) not in graph_ids]
                    recs = graph + supplement
                    used = "graphql+text-supplement" if supplement else "graphql"
                else:
                    recs, used = text, "text"
            self.note = f"strategy={used} (graphql={len(graph)}, text={len(text)})"
            if strategy == "auto" and used == "text" and graph:
                self.note += " — GraphQL result looked incomplete, used the page text"
            elif strategy == "auto" and used == "graphql+text-supplement":
                self.note += " — GraphQL primary + missing page variants supplemented"
        if not recs:
            raise RuntimeError("Hamrahtel returned zero products (site unreachable, blocked, or page layout changed)")
        self.raw_count = len(recs)
        self.catalog_titles = [r["title"] for r in recs][:3000]
        return recs


def debug_lines(raw_lines, n=120, context=15):
    """Numbered slice of the rendered page text around the first price line (to learn the real card layout)."""
    scraper = _scraper()
    first = next((i for i, x in enumerate(raw_lines) if scraper.is_price(x)), 0)
    a = max(0, first - context)
    return [f"{i:4d} | {x}" for i, x in enumerate(raw_lines[a:a + n], start=a)]


def dump_page(category="mobile", lines=120, timeout_ms=90000, max_scrolls=20, grep=""):
    """Diagnostics: print what the site really renders (text lines + JSON responses that contain prices)."""
    scraper = _scraper()
    from playwright.sync_api import sync_playwright
    url = scraper.CATEGORIES[category]
    out, json_hits, json_bodies = [], [], []
    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True)
        page = browser.new_page()

        def on_response(resp):
            try:
                if "json" in (resp.headers.get("content-type") or ""):
                    body = resp.text()
                    n = body.lower().count("price")
                    if n:
                        json_hits.append((n, len(body), resp.url[:140]))
                        json_bodies.append(body)
            except Exception:
                pass
        page.on("response", on_response)
        page.goto(url, wait_until="domcontentloaded", timeout=timeout_ms)
        page.wait_for_timeout(5000)
        scraper.scroll_page(page, max_scrolls)
        body = page.locator("body").inner_text(timeout=15000)
        try:
            hrefs = page.eval_on_selector_all("a[href]", "els => els.map(e => e.href)")
        except Exception:
            hrefs = []
        card_counts = {}
        for sel in ('[data-testid*="product"]', '[class*="product-card"]', '[class*="ProductCard"]', '[class*="product-item"]'):
            try:
                card_counts[sel] = page.locator(sel).count()
            except Exception:
                card_counts[sel] = "error"
        browser.close()
    raw = [c for c in (scraper.clean_text(x) for x in body.splitlines()) if c]
    out.append(f"URL: {url}")
    out.append(f"non-empty text lines: {len(raw)} | price-like lines: {sum(scraper.is_price(x) for x in raw)}")
    out.append(f"card selector counts: {card_counts}")
    out.append("JSON responses containing 'price' (count, bytes, url): " + str(sorted(json_hits, reverse=True)[:6]))
    if grep:
        out.append(f"--- lines matching {grep!r} (3 before / 6 after) ---")
        hits = [i for i, x in enumerate(raw) if grep.lower() in x.lower()][:6]
        for i in hits:
            out += [f"{j:4d} | {raw[j]}" for j in range(max(0, i - 3), min(len(raw), i + 7))] + ["  ..."]
        if not hits:
            out.append("(no line contains it)")
    out.append("links containing 'product': " + str([h for h in dict.fromkeys(hrefs) if "product" in h.lower()][:8]))
    out.append("--- rendered text around the first price line ---")
    out += debug_lines(raw, lines)
    if json_bodies:
        big = max(json_bodies, key=len)
        out.append(f"--- largest GraphQL/JSON response with prices ({len(big)} bytes), first 2500 chars ---")
        out.append(big[:2500])
    parsed = scraper.parse_body_lines(raw)
    out.append(f"--- parse_body_lines(): {len(parsed)} products; first 12 ---")
    out += [f"   {p}" for p in parsed[:12]]
    return "\n".join(out)
