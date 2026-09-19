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


EXIT_TELEGRAM = 6


@dataclass
class RunResult:
    exit_code: int
    doc: dict = field(default_factory=dict)
    summary: dict = field(default_factory=dict)
    message: str = ""
    offers: list = field(default_factory=list)
    watchlist: list = field(default_factory=list)
    watch_attrs: dict = field(default_factory=dict)
    settings: object = None
    match_report: list = field(default_factory=list)
    catalog_titles: dict = field(default_factory=dict)


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
        base_dir=".", http=None, now=None, send_telegram=True) -> RunResult:
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
                               base_dir, http, now, send_telegram)
    except LockError as exc:
        return RunResult(EXIT_LOCKED, message=str(exc))


def _run_locked(settings, ex, watchlist, source_cfgs, overrides, outdir, dry_run, require_all, base_dir, http, now,
                send_telegram=True):
    offers, status, degraded, catalogs = [], [], set(), {}
    for cfg in source_cfgs:
        t0 = time.monotonic()
        st = {"name": cfg.name, "status": "ok", "count": 0, "seconds": 0.0, "error": None,
              "currency_unit": cfg.currency_unit}
        try:
            src = build_source(cfg, settings, base_dir, http)
            got = src.fetch(watchlist)
            catalog = src.raw_count if src.raw_count is not None else len(got)
            st["count"], st["catalog_count"] = len(got), catalog
            catalogs[cfg.name] = list(src.catalog_titles) or [o.raw_title for o in got]
            # health = size of the WHOLE catalog we saw, not of the watchlist-filtered subset
            if catalog < cfg.min_expected_products:
                st["status"] = "degraded"
                st["error"] = f"only {catalog} products in catalog; expected >= {cfg.min_expected_products}"
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
    exit_code, tg_status = EXIT_OK, "disabled (settings: telegram_enabled=false)"
    current = {history.key(p["id"], v["variant"]): {"price": v["winner"]["price_toman"], "source": v["winner"]["source"]}
               for p in products for v in p["variants"] if v["winner"]}
    if not dry_run:
        report.write_all(outdir, doc, match_report, run_summary)
        if settings.telegram_enabled and not send_telegram:
            tg_status = "skipped (--no-telegram)"
        elif settings.telegram_enabled:
            changed = current != prev
            if settings.telegram_only_on_change and not changed and current:
                tg_status = "unchanged since last run: not sent"
            else:
                tok, chat = os.environ.get("TELEGRAM_BOT_TOKEN"), os.environ.get("TELEGRAM_CHAT_ID")
                if not (tok and chat):
                    tg_status, exit_code = "FAILED: TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID are not set", EXIT_TELEGRAM
                else:
                    try:
                        parts = telegram.send(tok, chat, report.build_telegram(doc), settings.telegram_max_message_len,
                                              dry_run=settings.telegram_dry_run)
                        tg_status = (f"dry-run: {len(parts)} message(s) NOT sent (telegram_dry_run=true)"
                                     if settings.telegram_dry_run else f"sent {len(parts)} message(s)")
                    except Exception as exc:               # never leak the bot token (it is inside the request URL)
                        tg_status, exit_code = "FAILED: " + str(exc).replace(tok, "***"), EXIT_TELEGRAM
        history.append(settings.history_file, products, run_at)
    else:
        tg_status = "dry-run: nothing written or sent"
    summary["telegram"] = tg_status
    doc["summary"] = summary
    return RunResult(exit_code, doc=doc, summary={**summary, "sources": status}, message=tg_status if exit_code else "ok",
                     offers=offers, watchlist=watchlist, watch_attrs=watch_attrs, settings=settings,
                     match_report=match_report, catalog_titles=catalogs)


def closest_catalog_titles(watch, watch_attrs, titles, ex: Extractor, n=3):
    """Catalog titles most similar to a watchlist product (helps to see why nothing matched: 'Note 15' vs 'Note 14')."""
    want = set(watch_attrs.core)
    scored = []
    for t in dict.fromkeys(titles):
        a = ex.parse(t)
        overlap = len(want & set(a.core))
        if overlap:
            scored.append((overlap + (0.5 if a.brand == watch.brand else 0), t))
    scored.sort(key=lambda x: -x[0])
    return [t for _, t in scored[:n]]
