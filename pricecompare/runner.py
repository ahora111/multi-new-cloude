from __future__ import annotations
import logging
import os
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from . import history, report, telegram
from .config import ConfigError, load_overrides, load_settings, load_sources, load_watchlist
from .extract import Extractor
from .lock import RunLock
from .matcher import assign
from .pricing import build_product, scale_check
from .sources import build_source

log = logging.getLogger("pricecompare")
EXIT_OK, EXIT_ALL_FAILED, EXIT_REQUIRE_ALL, EXIT_CONFIG, EXIT_LOCKED = 0, 2, 3, 4, 5


@dataclass
class RunResult:
    exit_code: int
    doc: dict = field(default_factory=dict)
    summary: dict = field(default_factory=dict)
    message: str = ""


def enrich(off, ex: Extractor):
    a = ex.parse(off.raw_title, off.raw_brand, off.raw_color, off.raw_storage, off.raw_ram)
    off.brand, off.model_core, off.tiers = a.brand, a.core, a.tiers
    off.storage_gb, off.ram_gb, off.color = a.storage_gb, a.ram_gb, a.color
    off.region, off.network, off.condition = a.region, a.network, a.condition
    if off.price_raw is not None:
        # the ONLY place where the rial->toman conversion happens (unit is declared per source)
        off.price_toman = off.price_raw / 10.0 if off.currency_unit_raw == "rial" else off.price_raw
    return off


def run(config_dir="config", output_dir=None, dry_run=False, only_source=None, require_all=False,
        base_dir=".", http=None, now=None) -> RunResult:
    try:
        settings = load_settings(config_dir)
        ex = Extractor(settings.dictionaries_file)
        watchlist = load_watchlist(config_dir, ex)
        source_cfgs = load_sources(config_dir)
        overrides = load_overrides(config_dir)
    except ConfigError as exc:
        return RunResult(EXIT_CONFIG, message=f"config error: {exc}")
    outdir = output_dir or settings.output_dir
    now = now or datetime.now(timezone.utc)
    if only_source:
        source_cfgs = [c for c in source_cfgs if c.name == only_source]
        if not source_cfgs:
            return RunResult(EXIT_CONFIG, message=f"config error: no source named {only_source!r}")
    source_cfgs = [c for c in source_cfgs if c.enabled]
    if not source_cfgs:
        return RunResult(EXIT_CONFIG, message="config error: no enabled source")

    from .lock import LockError
    try:
        with RunLock(settings.lock_file, settings.lock_stale_minutes):
            return _run_locked(settings, ex, watchlist, source_cfgs, overrides, outdir, dry_run, require_all,
                               base_dir, http, now)
    except LockError as exc:
        return RunResult(EXIT_LOCKED, message=str(exc))


def _run_locked(settings, ex, watchlist, source_cfgs, overrides, outdir, dry_run, require_all, base_dir, http, now):
    offers, status, degraded = [], [], set()
    for cfg in source_cfgs:
        t0 = time.monotonic()
        st = {"name": cfg.name, "status": "ok", "count": 0, "seconds": 0.0, "error": None,
              "currency_unit": cfg.currency_unit}
        try:
            src = build_source(cfg, settings, base_dir, http)
            got = src.fetch(watchlist)
            st["count"] = len(got)
            if len(got) < cfg.min_expected_products:
                st["status"] = "degraded"
                st["error"] = f"only {len(got)} products; expected >= {cfg.min_expected_products}"
                if cfg.degraded_excluded:
                    degraded.add(cfg.name)
            offers.extend(got)
        except Exception as exc:                       # one broken source must not stop the others
            st["status"], st["error"] = "failed", f"{exc.__class__.__name__}: {exc}"
            log.error("source %s failed: %s", cfg.name, st["error"])
        st["seconds"] = round(time.monotonic() - t0, 2)
        status.append(st)

    failed = [s for s in status if s["status"] == "failed"]
    bad = [s for s in status if s["status"] != "ok"]
    summary = {"sources_ok": sum(s["status"] == "ok" for s in status), "sources_failed": len(failed),
               "sources_degraded": sum(s["status"] == "degraded" for s in status)}
    if all(s["status"] == "failed" for s in status) or not offers:
        msg = "all sources failed or returned nothing; previous output kept untouched"
        return RunResult(EXIT_ALL_FAILED, summary={**summary, "sources": status}, message=msg)
    if require_all and bad:
        return RunResult(EXIT_REQUIRE_ALL, summary={**summary, "sources": status},
                         message="--require-all-sources: " + ", ".join(f"{s['name']}={s['status']}" for s in bad))

    for o in offers:
        enrich(o, ex)
    watch_attrs = {w.id: ex.parse(w.model) for w in watchlist}
    matched, match_report, review_queue = assign(offers, watchlist, watch_attrs, settings, overrides)
    priorities = {c.name: c.priority for c in source_cfgs}
    products = [build_product(w, matched[w.id], priorities, settings, now, degraded) for w in watchlist]

    warnings = [f"منبع «{s['name']}» {'خراب شد' if s['status'] == 'failed' else 'مشکوک است'}: {s['error']} — نتیجه ممکن است ناقص باشد"
                for s in bad]
    warnings += scale_check(products, settings)
    prev = history.last_prices(settings.history_file)
    warnings += history.price_changes(products, prev, settings.history_alert_pct)
    for p in products:
        for v in p["variants"]:
            v["single_source"] = len({o["source"] for o in v["offers"] if o["valid"]}) == 1

    not_found = [p["id"] for p in products if p["status"] == "not_found"]
    summary.update({
        "offers_total": len(offers), "products_total": len(products),
        "products_found": sum(p["status"] == "found" for p in products), "products_not_found": len(not_found),
        "review_items": len(review_queue),
        "suspect_offers": sum(o["suspect"] for p in products for v in p["variants"] for o in v["offers"]),
        "needs_review_variants": sum(v["needs_review"] for p in products for v in p["variants"])})
    run_at = now.isoformat()
    doc = report.build_document(run_at, products, not_found, review_queue, status, warnings)
    doc["summary"] = summary
    run_summary = {"run_at": run_at, "summary": summary, "sources": status, "warnings": warnings}
    if not dry_run:
        report.write_all(outdir, doc, match_report, run_summary)
        history.append(settings.history_file, products, run_at)
        if settings.telegram_enabled:
            tok, chat = os.environ.get("TELEGRAM_BOT_TOKEN"), os.environ.get("TELEGRAM_CHAT_ID")
            if not (tok and chat):
                raise ConfigError("telegram_enabled but TELEGRAM_BOT_TOKEN/TELEGRAM_CHAT_ID are not set")
            telegram.send(tok, chat, report.build_markdown(doc), settings.telegram_max_message_len,
                          dry_run=settings.telegram_dry_run)
    return RunResult(EXIT_OK, doc=doc, summary={**summary, "sources": status}, message="ok")
