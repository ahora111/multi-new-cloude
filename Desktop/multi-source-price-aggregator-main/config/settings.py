import os
from dataclasses import dataclass
from dotenv import load_dotenv

load_dotenv()

def as_bool(v, default=False):
    if v is None:
        return default
    return v.lower() in ("1", "true", "yes", "on")

@dataclass
class Settings:
    dry_run: bool = as_bool(os.getenv("DRY_RUN"), True)
    log_level: str = os.getenv("LOG_LEVEL", "INFO")
    match_auto_threshold: float = float(os.getenv("MATCH_AUTO_THRESHOLD", "90"))
    match_review_threshold: float = float(os.getenv("MATCH_REVIEW_THRESHOLD", "75"))
    max_price_age_minutes: int = int(os.getenv("MAX_PRICE_AGE_MINUTES", "60"))
    outlier_ratio: float = float(os.getenv("OUTLIER_RATIO", "3.0"))
    state_file: str = os.getenv("STATE_FILE", "data/state.json")
    # Hamrahtel / Playwright runtime settings (kept configurable for CI and local runs).
    scrape_attempts: int = int(os.getenv("SCRAPE_ATTEMPTS", "3"))
    page_timeout_ms: int = int(os.getenv("PAGE_TIMEOUT_MS", "90000"))
    max_scrolls: int = int(os.getenv("MAX_SCROLLS", "20"))
    legacy_skip_items: int = int(os.getenv("LEGACY_SKIP_ITEMS", "25"))

settings = Settings()
