"""Strict config loading. Unknown keys are ERRORS so no setting can be silently ignored."""
from __future__ import annotations
import os
<<<<<<< HEAD
import re
=======
>>>>>>> f17e6a59f11b4c55f7e0c722244e8621d106d9dc
from dataclasses import dataclass, field, fields
from pathlib import Path
from typing import Optional
import yaml
from .models import WatchItem


class ConfigError(Exception):
    pass


@dataclass
class Settings:
    match_auto_threshold: float = 95.0       # fuzzy core score >= this -> AUTO_MATCH
    match_review_threshold: float = 85.0     # between review..auto -> REVIEW
    review_as_match: bool = False            # treat REVIEW offers as matches for pricing
    max_price_age_minutes: int = 180         # older offers are ignored
    outlier_ratio: float = 3.0               # median/ratio .. median*ratio band
    history_alert_pct: float = 15.0          # warn when winner price moves more than this
    scale_check_min_pairs: int = 3           # min common variants to test toman/rial mismatch
    output_dir: str = "data/out"
    history_file: str = "data/history.jsonl"
    cache_dir: str = "data/cache"
    cache_ttl_seconds: int = 300
    lock_file: str = "data/run.lock"
    lock_stale_minutes: int = 60
    dictionaries_file: Optional[str] = None
    telegram_enabled: bool = False
    telegram_dry_run: bool = True
    telegram_only_on_change: bool = True     # send only when something changed since the LAST MESSAGE
    telegram_min_change_pct: float = 0.5     # ...where 'changed' = a winner price moved >= this % (or a variant appeared/vanished)
    telegram_state_file: str = "data/telegram_state.json"   # prices as of the last message actually sent
    telegram_group_by: str = "brand"          # brand | product | none  -> how the report is split into separate posts
    telegram_mode: str = "full"               # full = every phone each time | changes_only = only variants whose price moved
    telegram_show_links: bool = True
    telegram_max_messages: int = 60           # safety cap (Telegram allows ~20 posts/minute per group)
    telegram_max_message_len: int = 2800
<<<<<<< HEAD
    # ---- V2: shared hourly update cycle ----
    cycle_interval_minutes: int = 60         # default cadence of the shared update cycle (watch mode / scheduler)
    cycle_max_workers: int = 3               # sources fetched in parallel; each keeps its own rate limit
    timezone: str = "Asia/Tehran"            # all order/delivery/report-time calculations
    # ---- V2: per-source price tracking & drop alerts ----
    price_alert_drop_pct: float = 1.0        # vendor drop alert threshold (% decrease of a vendor's own valid price)
    price_alert_market_beat_pct: float = 0.5 # best-market-price alert: undercut the previous market lowest by this %
    vendor_price_compare_max_hours: int = 48  # a vendor baseline older than this is NEVER used for % (base re-registered)
    source_state_file: str = "data/source_state.json"        # last fetch/status per source (survives restarts)
    source_snapshots_dir: str = "data/source_snapshots"      # last good offers per source (for min_fetch_interval)
    alerts_file: str = "data/alerts.jsonl"   # every detected price change, even below the telegram threshold
    # ---- V2: telegram scheduling (full report and alerts are INDEPENDENT) ----
    telegram_alerts_enabled: bool = True     # send drop/opportunity alerts immediately when detected
    telegram_alert_state_file: str = "data/telegram_alert_state.json"   # dedup: last alerted price per alert
    telegram_report_times: list = field(default_factory=list)           # e.g. ["09:00", "21:00"] Tehran; empty = every cycle
    telegram_report_grace_minutes: int = 20  # a scheduled slot may fire up to this many minutes late
    telegram_report_state_file: str = "data/telegram_report_state.json"  # last sent slot ("YYYY-MM-DD HH:MM")

    def tz(self):
        from zoneinfo import ZoneInfo
        return ZoneInfo(self.timezone)
=======
>>>>>>> f17e6a59f11b4c55f7e0c722244e8621d106d9dc


@dataclass
class SourceConfig:
    name: str
    type: str
    currency_unit: str                       # "toman" | "rial"  (mandatory, explicit)
    enabled: bool = True
    priority: int = 100                      # lower wins ties
    min_expected_products: int = 0
    degraded_excluded: bool = True           # offers of a degraded source never win
    options: dict = field(default_factory=dict)   # everything type-specific


def _load(path: Path):
    if not path.exists():
        raise ConfigError(f"config file not found: {path}")
    try:
        return yaml.safe_load(open(path, encoding="utf-8")) or {}
    except yaml.YAMLError as exc:
        raise ConfigError(f"{path}: invalid YAML ({exc})")


def load_settings(config_dir: str) -> Settings:
    p = Path(config_dir) / "settings.yaml"
    data = _load(p) if p.exists() else {}
    known = {f.name for f in fields(Settings)}
    bad = set(data) - known
    if bad:
        raise ConfigError(f"settings.yaml: unknown keys {sorted(bad)}; allowed: {sorted(known)}")
    s = Settings(**data)
    if not (0 < s.match_review_threshold <= s.match_auto_threshold <= 100):
        raise ConfigError("settings.yaml: need 0 < match_review_threshold <= match_auto_threshold <= 100")
    if s.outlier_ratio < 1:
        raise ConfigError("settings.yaml: outlier_ratio must be >= 1")
    if s.telegram_group_by not in ("brand", "product", "none"):
        raise ConfigError("settings.yaml: telegram_group_by must be brand|product|none")
    if s.telegram_mode not in ("full", "changes_only"):
        raise ConfigError("settings.yaml: telegram_mode must be full|changes_only")
    if s.telegram_min_change_pct < 0:
        raise ConfigError("settings.yaml: telegram_min_change_pct must be >= 0")
<<<<<<< HEAD
    # ---- V2 validation ----
    if s.cycle_interval_minutes < 1:
        raise ConfigError("settings.yaml: cycle_interval_minutes must be >= 1")
    if not (1 <= s.cycle_max_workers <= 16):
        raise ConfigError("settings.yaml: cycle_max_workers must be between 1 and 16")
    if s.price_alert_drop_pct < 0 or s.price_alert_market_beat_pct < 0:
        raise ConfigError("settings.yaml: price_alert_drop_pct / price_alert_market_beat_pct must be >= 0")
    if s.vendor_price_compare_max_hours < 1:
        raise ConfigError("settings.yaml: vendor_price_compare_max_hours must be >= 1")
    try:
        s.tz()
    except Exception as exc:
        raise ConfigError(f"settings.yaml: unknown timezone {s.timezone!r} ({exc})")
    for t in s.telegram_report_times:
        if not (isinstance(t, str) and re.fullmatch(r"\d{1,2}:\d{2}", t.strip()) and 0 <= int(t.split(":")[0]) <= 23 and 0 <= int(t.split(":")[1]) <= 59):
            raise ConfigError(f"settings.yaml: telegram_report_times entries must be 'HH:MM' (00-23:00-59), got {t!r}")
    if s.telegram_report_grace_minutes < 0:
        raise ConfigError("settings.yaml: telegram_report_grace_minutes must be >= 0")
=======
>>>>>>> f17e6a59f11b4c55f7e0c722244e8621d106d9dc
    return s


def _opt_int(v, where):
    if v is None:
        return None
    try:
        return int(str(v).lower().replace("gb", "").strip())
    except ValueError:
        raise ConfigError(f"{where}: expected a number, got {v!r}")


@dataclass
class Discovery:
    enabled: bool = False
    min_sources: int = 1                 # 1 = list every phone; 2 = only phones sold by >= 2 shops
    brands: list = field(default_factory=list)      # optional filter, e.g. [apple, samsung]
    exclude_regex: str = ""              # skip titles matching this (e.g. feature phones)


def load_discovery(config_dir: str) -> Discovery:
    raw = (_load(Path(config_dir) / "watchlist.yaml").get("discovery")) or {}
    known = {"enabled", "min_sources", "brands", "exclude_regex"}
    if set(raw) - known:
        raise ConfigError(f"watchlist.yaml discovery: unknown keys {sorted(set(raw) - known)}")
    d = Discovery(enabled=bool(raw.get("enabled", False)), min_sources=int(raw.get("min_sources", 1)),
                  brands=[str(b).lower() for b in raw.get("brands") or []], exclude_regex=str(raw.get("exclude_regex") or ""))
    if d.min_sources < 1:
        raise ConfigError("watchlist.yaml discovery: min_sources must be >= 1")
    return d


def load_watchlist(config_dir: str, extractor) -> list:
    data = _load(Path(config_dir) / "watchlist.yaml")
    rows = data.get("products") or []
    if not isinstance(rows, list):
        raise ConfigError("watchlist.yaml: 'products' must be a list")
    if not rows:
        if load_discovery(config_dir).enabled:
            return []
        raise ConfigError("watchlist.yaml: 'products' must be a non-empty list (or enable `discovery`)")
    out, seen = [], set()
    allowed = {"id", "brand", "model", "storage", "ram", "region", "condition", "colors", "max_price", "barcodes"}
    for i, r in enumerate(rows):
        where = f"watchlist.yaml products[{i}]"
        if not isinstance(r, dict):
            raise ConfigError(f"{where}: must be a mapping")
        bad = set(r) - allowed
        if bad:
            raise ConfigError(f"{where}: unknown keys {sorted(bad)}")
        for req in ("id", "brand", "model"):
            if not r.get(req):
                raise ConfigError(f"{where}: '{req}' is required")
        if r["id"] in seen:
            raise ConfigError(f"{where}: duplicate id {r['id']!r}")
        seen.add(r["id"])
        cond = r.get("condition")
        if cond in ("non_active", "non-active"):
            cond = "nonactive"
        if cond not in (None, "new", "active", "nonactive"):
            raise ConfigError(f"{where}: condition must be new|active|nonactive")
        region = extractor.normalize_text(r["region"]) if r.get("region") else None
        if region:
            region = extractor._find(extractor._regions, region)[0] or region
        colors = r.get("colors") or ["any"]
        colors = ["any"] if "any" in colors else [extractor.color_of(c, explicit=True) for c in colors]
        out.append(WatchItem(
            id=str(r["id"]), brand=extractor.canonical_brand(r["brand"]) or extractor.normalize_text(r["brand"]),
            model=str(r["model"]), storage_gb=_opt_int(r.get("storage"), where + ".storage"),
            ram_gb=_opt_int(r.get("ram"), where + ".ram"), region=region, condition=cond,
            colors=colors, max_price=r.get("max_price"), barcodes=[str(b) for b in r.get("barcodes") or []]))
    return out


def load_sources(config_dir: str) -> list:
    data = _load(Path(config_dir) / "sources.yaml")
    rows = data.get("sources")
    if not isinstance(rows, list) or not rows:
        raise ConfigError("sources.yaml: 'sources' must be a non-empty list")
    out, seen = [], set()
    for i, r in enumerate(rows):
        where = f"sources.yaml sources[{i}]"
        for req in ("name", "currency_unit"):
            if not r.get(req):
                raise ConfigError(f"{where}: '{req}' is required (currency_unit must be explicit: toman|rial)")
        if not (r.get("type") or r.get("class")):
            raise ConfigError(f"{where}: either 'type' or 'class' is required")
        if r["currency_unit"] not in ("toman", "rial"):
            raise ConfigError(f"{where}: currency_unit must be 'toman' or 'rial'")
        if r["name"] in seen:
            raise ConfigError(f"{where}: duplicate source name {r['name']!r}")
        seen.add(r["name"])
        core = {"name", "type", "currency_unit", "enabled", "priority", "min_expected_products", "degraded_excluded"}
        out.append(SourceConfig(
            name=r["name"], type=r.get("type") or "custom", currency_unit=r["currency_unit"],
            enabled=bool(r.get("enabled", True)), priority=int(r.get("priority", 100)),
            min_expected_products=int(r.get("min_expected_products", 0)),
            degraded_excluded=bool(r.get("degraded_excluded", True)),
            options={k: v for k, v in r.items() if k not in core}))
    return out


def load_overrides(config_dir: str) -> dict:
    p = Path(config_dir) / "overrides.yaml"
    data = _load(p) if p.exists() else {}
    merges = data.get("color_merge") or []
    for i, m in enumerate(merges):
        if not (isinstance(m, dict) and m.get("watch_id") and isinstance(m.get("colors"), list) and m.get("as")):
            raise ConfigError(f"overrides.yaml color_merge[{i}]: need watch_id, colors: [..], as")
    return {"force_match": data.get("force_match") or [], "force_split": data.get("force_split") or [], "color_merge": merges}
