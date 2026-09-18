from dataclasses import dataclass, field
from typing import Any, Optional
from datetime import datetime, timezone

def now_iso():
    return datetime.now(timezone.utc).isoformat()

@dataclass
class SourceProduct:
    source: str
    source_product_id: str
    brand: str
    product_name: str
    price: Optional[float] = None
    stock: str = "UNKNOWN"
    url: str = ""
    image: str = ""
    sku: str = ""
    barcode: str = ""
    model: str = ""
    variant: str = ""
    storage: str = ""
    ram: str = ""
    color: str = ""
    category: str = "unknown"
    currency: str = "IRT"
    timestamp: str = field(default_factory=now_iso)
    attributes: dict[str, Any] = field(default_factory=dict)

@dataclass
class MatchResult:
    canonical_id: str
    confidence: float
    status: str  # AUTO_MATCH / REVIEW / NEW

@dataclass
class CanonicalProduct:
    canonical_id: str
    brand: str
    model: str
    category: str
    attributes: dict[str, Any]
    source_products: list[SourceProduct] = field(default_factory=list)
    best_price: Optional[float] = None
    best_source: Optional[str] = None
    best_url: Optional[str] = None
    best_stock: Optional[str] = None
    # Best valid offer for each normalized variant (primarily color).
    variant_results: dict[str, dict[str, Any]] = field(default_factory=dict)

@dataclass
class RunSummary:
    sources_ok: int = 0
    sources_failed: int = 0
    raw_products: int = 0
    canonical_products: int = 0
    matched: int = 0
    review: int = 0
    invalid_prices: int = 0
    published: int = 0
    skipped: int = 0
    failed_destinations: int = 0

    def to_text(self):
        return (
            "==============================\n"
            "SYNC SUMMARY\n"
            "==============================\n"
            f"Sources OK: {self.sources_ok}\n"
            f"Sources Failed: {self.sources_failed}\n"
            f"Raw Products: {self.raw_products}\n"
            f"Canonical Products: {self.canonical_products}\n"
            f"Auto Matched: {self.matched}\n"
            f"Needs Review: {self.review}\n"
            f"Invalid Prices: {self.invalid_prices}\n"
            f"Published: {self.published}\n"
            f"Skipped: {self.skipped}\n"
            f"Destination Failures: {self.failed_destinations}\n"
        )
