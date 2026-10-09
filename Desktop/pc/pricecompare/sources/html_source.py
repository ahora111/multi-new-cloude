from urllib.parse import urljoin
from bs4 import BeautifulSoup
from .base import Source


def _sel(node, spec):
    """'css' -> text ; 'css::attr(href)' -> attribute ; '' -> None. '@attr(x)' reads from the item itself."""
    if not spec:
        return None
    if spec.startswith("@attr("):
        return node.get(spec[6:-1])
    css, _, attr = spec.partition("::attr(")
    el = node.select_one(css) if css else node
    if el is None:
        return None
    return el.get(attr.rstrip(")")) if attr else el.get_text(" ", strip=True)


class HtmlSource(Source):
    """options: path|url|urls|search_url, item_selector, fields{title,price,url,id,color,image,...},
    out_of_stock_selector (presence => OUT_OF_STOCK), stock (selector) , base_url"""
    type_name = "html"

    def records(self, watchlist):
        f = self.o.get("fields") or {}
        if not self.o.get("item_selector") or "title" not in f or "price" not in f:
            raise ValueError(f"source {self.name}: item_selector, fields.title and fields.price are required")
        out = []
        for loc in self.locations(watchlist):
            soup = BeautifulSoup(self.read(loc), "lxml")
            for node in soup.select(self.o["item_selector"]):
                g = lambda k: _sel(node, f.get(k))                           # noqa: E731
                url = g("url") or ""
                if url and self.o.get("base_url"):
                    url = urljoin(self.o["base_url"], url)
                oos = self.o.get("out_of_stock_selector")
                stock = g("stock")
                if oos and node.select_one(oos):
                    stock = "out_of_stock"
                elif stock is None and oos:
                    stock = "in_stock"
                out.append({"id": g("id"), "title": g("title"), "price": g("price"), "stock": stock,
                            "url": url, "image": g("image"), "color": g("color"), "storage": g("storage"),
                            "ram": g("ram"), "brand": g("brand")})
        return out
