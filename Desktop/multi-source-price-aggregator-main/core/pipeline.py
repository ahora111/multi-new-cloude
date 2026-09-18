from .models import RunSummary
from .normalizer import normalized_product
from .matcher import match_products
from .pricing import choose_lowest
from utils.logging import get_logger

class Pipeline:
    def __init__(self, sources, destinations):
        self.sources = sources
        self.destinations = destinations
        self.log = get_logger("pipeline")

    def run(self):
        summary = RunSummary()
        all_products = []

        for source in self.sources:
            try:
                products = source.fetch()
                products = [normalized_product(p) for p in products]
                all_products.extend(products)
                summary.sources_ok += 1
                self.log.info("%s: %s products", source.name, len(products))
            except Exception as exc:
                summary.sources_failed += 1
                self.log.exception("%s failed: %s", source.name, exc)

        summary.raw_products = len(all_products)

        source_counts = {}
        for p in all_products:
            source_counts[p.source] = source_counts.get(p.source, 0) + 1
        self.log.info("========================================")
        self.log.info("CROSS-SOURCE COMPARISON: %s", ", ".join(f"{k}={v}" for k, v in sorted(source_counts.items())))
        self.log.info("Comparing ALL fetched products across different sources")
        self.log.info("========================================")

        canonicals, match_status = match_products(all_products)
        summary.matched = match_status["matched"]
        summary.review = match_status["review"]
        summary.canonical_products = len(canonicals)

        for product in canonicals:
            choose_lowest(product)

        compared = sum(1 for p in canonicals if len({sp.source for sp in p.source_products}) > 1)
        self.log.info("Cross-source matched products: %s", compared)
        self.log.info("Products with one source only: %s", len(canonicals) - compared)

        for destination in self.destinations:
            try:
                if destination.publish(canonicals):
                    summary.published += 1
                else:
                    summary.skipped += 1
            except Exception as exc:
                summary.failed_destinations += 1
                self.log.exception("Destination failed: %s", exc)

        return summary
