import json
from urllib.parse import urljoin
from .base import Source


def dig(obj, path):
    """dotted path: 'data.items', 'price.amount', 'variants.0.color'."""
    if path in (None, ""):
        return obj
    for part in str(path).split("."):
        if isinstance(obj, dict):
            obj = obj.get(part)
        elif isinstance(obj, list) and part.isdigit() and int(part) < len(obj):
            obj = obj[int(part)]
        else:
            return None
    return obj


class JsonSource(Source):
    """options: path|url|urls|search_url, items_path, fields{title,price,stock,url,id,color,image,storage,ram,brand}, base_url"""
    type_name = "json"

    def records(self, watchlist):
        f = self.o.get("fields") or {}
        if "title" not in f or "price" not in f:
            raise ValueError(f"source {self.name}: fields.title and fields.price are required")
        out = []
        for loc in self.locations(watchlist):
            data = json.loads(self.read(loc))
            items = dig(data, self.o.get("items_path"))
            if not isinstance(items, list):
                raise ValueError(f"source {self.name}: items_path {self.o.get('items_path')!r} is not a list")
            for it in items:
                g = lambda k: dig(it, f.get(k)) if f.get(k) else None      # noqa: E731
                url = g("url") or ""
                if url and self.o.get("base_url"):
                    url = urljoin(self.o["base_url"], str(url))
                out.append({"id": g("id"), "title": g("title"), "price": g("price"), "stock": g("stock"),
                            "url": url, "image": g("image"), "color": g("color"), "storage": g("storage"),
                            "ram": g("ram"), "brand": g("brand"),
                            "extra": {"barcode": g("barcode")} if g("barcode") else {}})
        return out
