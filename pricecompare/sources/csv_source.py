import csv
import io
from .base import Source


class CsvSource(Source):
    """options: path|url, columns{title,price,stock,url,id,color,...}, delimiter"""
    type_name = "csv"

    def records(self, watchlist):
        cols = self.o.get("columns") or {}
        if "title" not in cols or "price" not in cols:
            raise ValueError(f"source {self.name}: columns.title and columns.price are required")
        out = []
        for loc in self.locations(watchlist):
            reader = csv.DictReader(io.StringIO(self.read(loc)), delimiter=self.o.get("delimiter", ","))
            for row in reader:
                g = lambda k: row.get(cols[k]) if cols.get(k) else None      # noqa: E731
                out.append({"id": g("id"), "title": g("title"), "price": g("price"), "stock": g("stock"),
                            "url": g("url"), "image": g("image"), "color": g("color"), "storage": g("storage"),
                            "ram": g("ram"), "brand": g("brand")})
        return out
