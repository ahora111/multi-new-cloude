from __future__ import annotations
from dataclasses import dataclass, field
from typing import Any, Optional

IN_STOCK, OUT_OF_STOCK, UNKNOWN_STOCK = "IN_STOCK", "OUT_OF_STOCK", "UNKNOWN"


@dataclass
class WatchItem:
    id: str
    brand: str
    model: str
    storage_gb: Optional[int] = None
    ram_gb: Optional[int] = None
    region: Optional[str] = None
    condition: Optional[str] = None      # new | active | nonactive
    colors: list = field(default_factory=lambda: ["any"])
    max_price: Optional[float] = None
    barcodes: list = field(default_factory=list)


@dataclass
class Offer:
    source: str
    source_offer_id: str
    raw_title: str
    price_raw: Optional[float]
    currency_unit_raw: str               # "toman" | "rial" (declared by the source)
    stock: str = UNKNOWN_STOCK
    url: str = ""
    image: str = ""
    fetched_at: str = ""
    raw_color: str = ""
    raw_storage: str = ""
    raw_ram: str = ""
    raw_brand: str = ""
    extra: dict = field(default_factory=dict)
    # filled by the pipeline
    price_toman: Optional[float] = None
    brand: str = ""
    model_core: list = field(default_factory=list)
    tiers: list = field(default_factory=list)
    storage_gb: Optional[int] = None
    ram_gb: Optional[int] = None
    color: str = ""
    region: str = ""
    network: str = ""
    condition: str = ""

    @property
    def key(self) -> str:
        return f"{self.source}:{self.source_offer_id}"


@dataclass
class HealthResult:
    ok: bool
    detail: str = ""
    count: int = 0
