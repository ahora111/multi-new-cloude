from __future__ import annotations
import json
import logging
import os
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from . import history, report, telegram
from .config import ConfigError, load_discovery, load_overrides, load_settings, load_sources, load_watchlist
from .discovery import discover
from .canonical import strong_identifier
from .delivery import load_schedules, estimate, SHIPPING_UNKNOWN_LABEL
from .extract import Extractor
from .lock import RunLock
from .matcher import AUTO, MatchResult, assign
from .pricing import build_product, scale_check, sort_products, sort_variants
from .sources import build_source

log = logging.getLogger("pricecompare")
EXIT_OK, EXIT_ALL_FAILED, EXIT_REQUIRE_ALL, EXIT_CONFIG, EXIT_LOCKED = 0, 2, 3, 4, 5


EXIT_TELEGRAM = 6

STATUS_FA = {"ok": "موفق", "degraded": "ناقص", "failed": "ناموفق", "stale": "داده قدیمی", "cached": "از کش"}


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


def dedupe_offers(offers):
    """Collapse duplicate Offer identities without collapsing legitimate variants.

    Source implementations are responsible for making ``source_offer_id`` variant-level
    when needed (for example, SKU rather than a shared product id). Once that contract is
    met, the pipeline key is intentionally only ``(source, source_offer_id)``.
    """
    def richness(o):
        return sum(bool(v) for v in (
            o.price_raw, o.url, o.image, o.raw_color, o.raw_storage, o.raw_ram,
            o.raw_brand, o.stock not in ("UNKNOWN", ""),
        ))

    unique = {}
    for o in offers:
        key = (o.source, str(o.source_offer_id))
        prev = unique.get(key)
        if prev is None or richness(o) > richness(prev):
            unique[key] = o
    return list(unique.values())


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
        discovery = load_discovery(config_dir)
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
                               base_dir, http, now, send_telegram, discovery, config_dir)
    except LockError as exc:
        return RunResult(EXIT_LOCKED, message=str(exc))


def _utcnow_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _age_minutes(iso: str, now: datetime) -> float:
    try:
        return (now - datetime.fromisoformat(iso)).total_seconds() / 60
    except (ValueError, TypeError):
        return 0.0


def _offers_all_older_than(offers, max_age_minutes: int, now: datetime) -> bool:
    """V2: a fetch whose every offer predates max_price_age_minutes is «داده قدیمی», never fresh."""
    if not offers:
        return False
    return all(_age_minutes(o.fetched_at, now) > max_age_minutes for o in offers if o.fetched_at) and \
        all(o.fetched_at for o in offers)


def _snapshot_path(snapshots_dir, name) -> Path:
    safe = "".join(c if c.isalnum() or c in "-_" else "_" for c in name)
    return Path(snapshots_dir) / f"{safe}.json"


def _save_snapshot(snapshots_dir, name, offers, catalog_titles) -> None:
    try:
        p = _snapshot_path(snapshots_dir, name)
        p.parent.mkdir(parents=True, exist_ok=True)
        data = [{"source": o.source, "source_offer_id": o.source_offer_id, "raw_title": o.raw_title,
                 "price_raw": o.price_raw, "currency_unit_raw": o.currency_unit_raw, "stock": o.stock,
                 "url": o.url, "image": o.image, "fetched_at": o.fetched_at, "raw_color": o.raw_color,
                 "raw_storage": o.raw_storage, "raw_ram": o.raw_ram, "raw_brand": o.raw_brand,
                 "extra": o.extra} for o in offers]
        fetched_at = next((o.fetched_at for o in offers if o.fetched_at), None) or _utcnow_iso()
        tmp = p.with_name(p.name + ".tmp")
        tmp.write_text(json.dumps({"saved_at": _utcnow_iso(), "fetched_at": fetched_at,
                                   "catalog_titles": catalog_titles, "offers": data},
                                  ensure_ascii=False), encoding="utf-8")
        tmp.replace(p)
    except OSError as exc:                                 # snapshots are an optimisation, never fatal
        log.warning("snapshot save failed for %s: %s", name, exc)


def _load_snapshot(snapshots_dir, name) -> tuple:
    """Returns (offers, catalog_titles, fetched_at) rebuilt from the last good fetch, or ([], [], None)."""
    try:
        p = _snapshot_path(snapshots_dir, name)
        if not p.exists():
            return [], [], None
        data = json.loads(p.read_text(encoding="utf-8"))
        from .models import Offer
        offers = [Offer(source=d["source"], source_offer_id=d["source_offer_id"], raw_title=d["raw_title"],
                        price_raw=d["price_raw"], currency_unit_raw=d["currency_unit_raw"], stock=d["stock"],
                        url=d.get("url", ""), image=d.get("image", ""), fetched_at=d.get("fetched_at", ""),
                        raw_color=d.get("raw_color", ""), raw_storage=d.get("raw_storage", ""),
                        raw_ram=d.get("raw_ram", ""), raw_brand=d.get("raw_brand", ""),
                        extra=d.get("extra") or {}) for d in data.get("offers", [])]
        return offers, list(data.get("catalog_titles") or []), data.get("fetched_at")
    except (OSError, ValueError, KeyError) as exc:
        log.warning("snapshot load failed for %s: %s", name, exc)
        return [], [], None


def _fetch_source(cfg, settings, base_dir, http, discovery, watchlist, prev_state, now, allow_snapshot_write=True):
    """One source inside the shared cycle. Never raises: failures become status='failed' and the
    rest of the cycle continues. V2 statuses: ok / degraded / failed / stale / cached."""
    t0 = time.monotonic()
    started = _utcnow_iso()
    st = {"name": cfg.name, "status": "ok", "count": 0, "seconds": 0.0, "error": None,
          "currency_unit": cfg.currency_unit, "fetch_started_at": started}
    got, catalog_titles = [], []
    try:
        min_interval = int(cfg.options.get("min_fetch_interval_minutes") or 0)
        if min_interval > 0:
            last_ok = (prev_state.get(cfg.name) or {}).get("last_ok_fetch_at")
            if last_ok and _age_minutes(last_ok, now) < min_interval:
                snap_offers, snap_titles, snap_fetched_at = _load_snapshot(settings.source_snapshots_dir, cfg.name)
                if snap_offers:
                    got, catalog_titles = snap_offers, snap_titles
                    st["status"] = "cached"
                    # the REAL last extraction time is the snapshot's, not this attempt's
                    st["fetched_at"] = snap_fetched_at
                    st["note"] = (f"reused last good snapshot (min_fetch_interval_minutes={min_interval}); "
                                  f"fetched_at preserved")
        if st["status"] != "cached":
            # a shared HttpClient is not thread-safe -> in parallel cycles every source builds its own
            src = build_source(cfg, settings, base_dir, None if http is None else http)
            got = src.fetch([] if discovery.enabled else watchlist)   # discovery reads the WHOLE catalog
            catalog = src.raw_count if src.raw_count is not None else len(got)
            st["count"], st["catalog_count"] = len(got), catalog
            catalog_titles = list(src.catalog_titles) or [o.raw_title for o in got]
            st["note"] = src.note
            # health = size of the WHOLE catalog we saw, not of the watchlist-filtered subset
            if catalog < cfg.min_expected_products:
                st["status"] = "degraded"
                st["error"] = f"only {catalog} products in catalog; expected >= {cfg.min_expected_products}"
            elif allow_snapshot_write:
                _save_snapshot(settings.source_snapshots_dir, cfg.name, got, catalog_titles)
        if not st["count"]:
            st["count"] = len(got)
        if st["status"] in ("ok", "cached") and _offers_all_older_than(got, settings.max_price_age_minutes, now):
            st["status"], st["error"] = "stale", "all offers older than max_price_age_minutes (داده قدیمی)"
    except Exception as exc:                       # one broken source must not stop the others
        st["status"], st["error"] = "failed", f"{exc.__class__.__name__}: {exc}"
        log.error("source %s failed: %s", cfg.name, st["error"])
    st["seconds"] = round(time.monotonic() - t0, 2)
    if not st.get("fetched_at"):
        st["fetched_at"] = _utcnow_iso()
    st["status_fa"] = STATUS_FA.get(st["status"], st["status"])
    return st, got, catalog_titles


def _load_source_state(path) -> dict:
    return history.load_state(path)


def _save_source_state(path, state) -> None:
    history.save_state(path, state)


def _run_locked(settings, ex, watchlist, source_cfgs, overrides, outdir, dry_run, require_all, base_dir, http, now,
                send_telegram=True, discovery=None, config_dir="config"):
    from .config import Discovery
    discovery = discovery or Discovery()
    cycle_started = _utcnow_iso()
    t_cycle = time.monotonic()
    offers, status, degraded, catalogs = [], [], set(), {}
    prev_source_state = _load_source_state(settings.source_state_file)

    # ---- shared cycle: every enabled source, fetched in parallel (each keeps its own rate limit) ----
    workers = max(1, min(int(settings.cycle_max_workers), len(source_cfgs)))
    parallel = workers > 1 and http is None and len(source_cfgs) > 1
    log.info("cycle started: %d source(s), workers=%d (%s)", len(source_cfgs), workers,
             "parallel" if parallel else "sequential")
    if parallel:
        with ThreadPoolExecutor(max_workers=workers) as pool:
            futs = {pool.submit(_fetch_source, cfg, settings, base_dir, http, discovery, watchlist,
                                prev_source_state, now, not dry_run): cfg.name for cfg in source_cfgs}
            results = [f.result() for f in futs]
    else:
        results = [_fetch_source(cfg, settings, base_dir, http, discovery, watchlist,
                                 prev_source_state, now, not dry_run) for cfg in source_cfgs]
    by_name = {r[0]["name"]: r for r in results}
    new_source_state = dict(prev_source_state)
    for cfg in source_cfgs:                                       # deterministic config order everywhere
        st, got, titles = by_name[cfg.name]
        status.append(st)
        catalogs[cfg.name] = titles
        if st["status"] == "degraded" and cfg.degraded_excluded:
            degraded.add(cfg.name)
        offers.extend(got)          # cached snapshot offers DO compete — their age still guards freshness
        prev = dict(prev_source_state.get(cfg.name) or {})
        entry = {"last_attempt_at": st["fetch_started_at"], "last_status": st["status"],
                 "last_status_fa": st["status_fa"], "last_count": st["count"]}
        if st["status"] in ("ok", "degraded"):
            entry["last_ok_fetch_at"] = st["fetched_at"]
            entry["consecutive_failures"] = 0
        elif st["status"] == "failed":
            entry["consecutive_failures"] = int(prev.get("consecutive_failures") or 0) + 1
        else:
            entry["consecutive_failures"] = int(prev.get("consecutive_failures") or 0)
        if st["status"] == "cached":
            entry["last_ok_fetch_at"] = prev.get("last_ok_fetch_at")
        new_source_state[cfg.name] = entry
        log.info("source %s: %s (%s) in %.1fs (%d offers%s)", cfg.name, st["status"], st["status_fa"],
                 st["seconds"], st["count"],
                 f", catalog={st['catalog_count']}" if "catalog_count" in st else "")
    if not dry_run:
        _save_source_state(settings.source_state_file, new_source_state)
    log.info("all sources finished in %.1fs: %d offers collected", time.monotonic() - t_cycle, len(offers))

    # Enforce the global Offer identity contract at the pipeline boundary. A source may
    # discover the same product more than once (multiple pages, fallback URLs, or a
    # rendered/API duplicate), but one (source, source_offer_id) must yield one Offer.
    # Keep the richest record deterministically rather than letting duplicates reach
    # matching/pricing/reporting.
    offers = dedupe_offers(offers)

    failed = [s for s in status if s["status"] == "failed"]
    bad = [s for s in status if s["status"] not in ("ok", "cached")]
    summary = {"sources_ok": sum(s["status"] == "ok" for s in status), "sources_failed": len(failed),
               "sources_degraded": sum(s["status"] == "degraded" for s in status),
               "sources_stale": sum(s["status"] == "stale" for s in status),
               "sources_cached": sum(s["status"] == "cached" for s in status)}
    if all(s["status"] == "failed" for s in status) or not offers:
        msg = "all sources failed or returned nothing; previous output kept untouched"
        return RunResult(EXIT_ALL_FAILED, summary={**summary, "sources": status}, message=msg)
    if require_all and bad:
        return RunResult(EXIT_REQUIRE_ALL, summary={**summary, "sources": status},
                         message="--require-all-sources: " + ", ".join(f"{s['name']}={s['status']}" for s in bad))

    for o in offers:
        enrich(o, ex)
    log.info("matching %d offers against %d watchlist items ...", len(offers), len(watchlist))
    watch_attrs = {w.id: ex.parse(w.model) for w in watchlist}
    matched, match_report, review_queue = assign(offers, watchlist, watch_attrs, settings, overrides)
    for m in overrides["color_merge"]:                       # e.g. shop A says "blue", shop B says "light blue"
        for off, _ in matched.get(m["watch_id"], []):
            if off.color in m["colors"]:
                off.color = m["as"]
    dyn_items = []
    if discovery.enabled:                                    # every phone nobody asked for explicitly
        claimed = {(o.source, o.source_offer_id) for lst in matched.values() for o, _ in lst}
        claimed |= {(r["source"], r["offer_id"]) for r in review_queue}
        claimed |= {(x["source"], str(x["source_offer_id"])) for x in overrides["force_split"]}
        rest = [o for o in offers if (o.source, o.source_offer_id) not in claimed]
        for o in rest:
            o.brand = o.brand or ("other" if o.model_core else "")
        dyn_items, dyn_attrs, members = discover(rest, ex, settings, discovery, reserved_ids={w.id for w in watchlist})
        used = set()
        for w in dyn_items:
            matched[w.id] = [(o, MatchResult(AUTO, 100.0, w.id, ["discovery cluster"])) for o in members[w.id]]
            used |= {(o.source, o.source_offer_id) for o in members[w.id]}
        rest_keys = {(o.source, o.source_offer_id) for o in rest}
        rows = [{"source": o.source, "offer_id": o.source_offer_id, "title": o.raw_title,
                 "watch_id": next((w.id for w in dyn_items if o in members[w.id]), None),
                 "status": AUTO if (o.source, o.source_offer_id) in used else "NO_MATCH", "score": 100.0 if (o.source, o.source_offer_id) in used else 0.0,
                 "reasons": ["discovery cluster"] if (o.source, o.source_offer_id) in used else ["unusable for discovery (no brand/model/price or filtered out)"]}
                for o in rest]
        match_report = [r for r in match_report if (r["source"], r["offer_id"]) not in rest_keys] + rows
        watch_attrs.update(dyn_attrs)
    all_items = list(watchlist) + dyn_items
    dyn_ids = {w.id for w in dyn_items}
    priorities = {c.name: c.priority for c in source_cfgs}
    products = [build_product(w, matched[w.id], priorities, settings, now, degraded, watch_attrs.get(w.id)) for w in all_items]
    for p in products:
        p["origin"] = "discovered" if p["id"] in dyn_ids else "watchlist"
    if discovery.enabled and discovery.min_sources > 1:
        products = [p for p in products if p["origin"] == "watchlist" or
                    len({o["source"] for v in p["variants"] for o in v["offers"] if o["valid"]}) >= discovery.min_sources]

    warnings = [f"منبع «{s['name']}» {'خراب شد' if s['status'] == 'failed' else 'مشکوک است'}: {s['error']} — نتیجه ممکن است ناقص باشد"
                for s in bad]
    warnings += scale_check(products, settings)
    prev = history.last_prices(settings.history_file)
    warnings += history.price_changes(products, prev, settings.history_alert_pct)
    for p in products:
        for v in p["variants"]:
            v["single_source"] = len({o["source"] for o in v["offers"] if o["valid"]}) == 1

    # ---- V2: independent cheapest / fastest selection per colour + transparent incomplete flags ----
    schedules = {}
    try:
        schedules = load_schedules(Path(config_dir) / "delivery.yaml", settings.timezone)
    except Exception as exc:                    # delivery config problems never kill the price cycle
        warnings.append(f"تنظیمات سفارش/تحویل قابل خواندن نیست: {exc} — زمان تحویل «نامشخص» نمایش داده می‌شود")
    bad_enabled = {s["name"] for s in status if s["status"] not in ("ok", "cached")}
    attach_delivery_and_fastest(products, schedules, now, settings)
    mark_incomplete(products, source_cfgs, bad_enabled)

    # ---- V2: per-vendor price tracking, drop/opportunity alerts, cycle change log ----
    prev_record = history.last_record(settings.history_file)
    changes = history.detect_changes(products, prev_record, settings.price_alert_drop_pct,
                                     settings.price_alert_market_beat_pct, now.isoformat(),
                                     settings.vendor_price_compare_max_hours)
    changes_by_key = {}
    for c in changes:
        changes_by_key.setdefault(history.key(c["product_id"], c["variant"]), []).append(c)
    for p in products:
        for v in p["variants"]:
            rows = changes_by_key.get(history.key(p["id"], v["variant"]), [])
            v["source_changes"] = rows
            v["alerts"] = [c for c in rows if c.get("alert")]
    alerts = [c for c in changes if c.get("alert")]

    # ---- V2 §9: one shared order (most expensive -> cheapest) for EVERY output ----
    for p in products:
        sort_variants(p)
    products = sort_products(products)

    not_found = [p["id"] for p in products if p["status"] == "not_found"]
    no_price = [p.get("title") or p.get("label") or p["id"] for p in products if p["status"] == "no_valid_price"]
    summary.update({
        "offers_total": len(offers), "products_total": len(products), "products_discovered": len(dyn_ids & {p["id"] for p in products}),
        "products_found": sum(p["status"] == "found" for p in products), "products_not_found": len(not_found),
        "products_no_valid_price": len(no_price),
        "review_items": len(review_queue),
        "suspect_offers": sum(o["suspect"] for p in products for v in p["variants"] for o in v["offers"]),
        "needs_review_variants": sum(v["needs_review"] for p in products for v in p["variants"]),
        "price_changes_total": len(changes), "price_alerts_total": len(alerts)})
    run_at = now.isoformat()
    cycle = {"started_at": cycle_started, "finished_at": None, "interval_minutes": settings.cycle_interval_minutes,
             "timezone": settings.timezone, "parallel": parallel, "workers": workers}
    # Attach an auditable, source-independent identity trace to every match row.
    offer_by_key = {(o.source, str(o.source_offer_id)): o for o in offers}
    for row in match_report:
        off = offer_by_key.get((row.get("source"), str(row.get("offer_id"))))
        if not off:
            continue
        row.update({
            "normalized_title": ex.normalize_text(off.raw_title),
            "brand": off.brand,
            "model": " ".join(off.model_core),
            "tiers": list(off.tiers),
            "ram_gb": off.ram_gb,
            "storage_gb": off.storage_gb,
            "network": off.network,
            "raw_color": off.raw_color,
            "canonical_color": off.color or "unknown",
            "canonical_product_key": next((p.get("canonical_product_key") for p in products
                                            if any(o.get("source") == off.source and o.get("offer_id") == off.source_offer_id
                                                   for v in p.get("variants", []) for o in v.get("offers", []))), None),
        })
    doc = report.build_document(run_at, products, not_found, review_queue, status, warnings)
    doc["summary"] = summary
    doc["cycle"] = {**cycle, "finished_at": _utcnow_iso()}
    doc["price_changes"] = changes
    doc["alerts"] = alerts
    run_summary = {"run_at": run_at, "summary": summary, "sources": status, "warnings": warnings,
                   "cycle": doc["cycle"]}
    exit_code, tg_status = EXIT_OK, "disabled (settings: telegram_enabled=false)"
    current = {history.key(p["id"], v["variant"]): {"price": v["winner"]["price_toman"], "source": v["winner"]["source"]}
               for p in products for v in p["variants"] if v["winner"]}
    if not dry_run:
        report.write_all(outdir, doc, match_report, run_summary)
        history.append_alerts(settings.alerts_file, changes, run_at)
        if settings.telegram_enabled and not send_telegram:
            tg_status = "skipped (--no-telegram)"
        elif settings.telegram_enabled:
            tg_status, exit_code = _telegram_phase(settings, doc, products, current, alerts, run_at, now)
        history.append(settings.history_file, products, run_at)
    else:
        tg_status = "dry-run: nothing written or sent"
    summary["telegram"] = tg_status
    doc["summary"] = summary
    return RunResult(exit_code, doc=doc, summary={**summary, "sources": status}, message=tg_status if exit_code else "ok",
                     offers=offers, watchlist=all_items, watch_attrs=watch_attrs, settings=settings,
                     match_report=match_report, catalog_titles=catalogs)


def attach_delivery_and_fastest(products, schedules, now, settings) -> None:
    """Per colour: delivery estimate of every valid vendor (independent per source, Asia/Tehran),
    the FASTEST vendor (earliest arrival; ties -> cheaper price) and deltas vs the cheapest."""
    for p in products:
        for v in p["variants"]:
            est, src_min = {}, {}
            for o in v.get("offers", []):
                s = o["source"]
                if o.get("valid") and o.get("price_toman"):
                    src_min[s] = min(src_min.get(s, o["price_toman"]), o["price_toman"])
            for s in src_min:
                est[s] = estimate(schedules.get(s), now, s)
            v["delivery"] = {s: e.to_dict() for s, e in est.items()}
            ok_est = {s: e for s, e in est.items() if e.status == "ok" and e.delivery_at}
            fast = None
            if ok_est:
                s = sorted(ok_est, key=lambda x: (ok_est[x].delivery_at, src_min.get(x, float("inf")), x))[0]
                e = ok_est[s]
                fast = {"source": s, "price_toman": src_min.get(s), "delivery_at": e.to_dict()["delivery_at"],
                        "delivery_label": e.label, "order_deadline": e.to_dict()["order_deadline"],
                        "hours_from_now": e.to_dict()["hours_from_now"], "verified": e.verified,
                        "shipping_label": e.shipping_label}
            v["fastest"] = fast
            wn = v.get("winner")
            if wn:
                e = est.get(wn["source"])
                if e and e.status == "ok":
                    wn["delivery_label"] = e.label
                    wn["delivery_at"] = e.to_dict()["delivery_at"]
                    wn["order_deadline"] = e.to_dict()["order_deadline"]
                    wn["shipping_label"] = e.shipping_label
                else:
                    wn["delivery_label"] = ""
                    wn["shipping_label"] = SHIPPING_UNKNOWN_LABEL
            if fast and wn:
                diff_price = (src_min.get(fast["source"], 0) - wn["price_toman"]) if wn.get("price_toman") else None
                w_est = est.get(wn["source"])
                diff_hours = None
                if w_est and w_est.status == "ok" and w_est.delivery_at and fast.get("hours_from_now") is not None:
                    diff_hours = round((w_est.delivery_at - now.astimezone(w_est.delivery_at.tzinfo)).total_seconds() / 3600
                                       - fast["hours_from_now"], 1)
                v["deltas"] = {"fastest_price_minus_cheapest_toman": diff_price,
                               "cheapest_delivery_minus_fastest_hours": diff_hours}
            v["delivery_unknown"] = bool(src_min) and not ok_est


def mark_incomplete(products, source_cfgs, bad_enabled) -> None:
    """V2 §6/§8/§10: a failed/degraded source means the comparison is incomplete; a vendor that
    carries a product but has no valid price for ONE colour is never hidden («قیمت دریافت نشد»)."""
    enabled = {c.name for c in source_cfgs}
    for p in products:
        carrying = {o["source"] for v in p["variants"] for o in v["offers"]}
        p["comparison_incomplete"] = bool(bad_enabled & enabled)
        p["incomplete_reasons"] = [f"منبع «{s}» در این چرخه در دسترس نبود" for s in sorted(bad_enabled & enabled)]
        for v in p["variants"]:
            have = {o["source"] for o in v.get("offers", [])}
            miss = []
            for s in sorted(carrying - have):
                if s in bad_enabled:
                    miss.append({"source": s, "reason": "منبع ناموفق"})
                else:
                    miss.append({"source": s, "reason": "قیمت دریافت نشد"})
            for o in v.get("offers", []):
                if not o.get("valid") and o.get("source") in carrying:
                    reason = o.get("excluded_reason") or "نامعتبر"
                    miss.append({"source": o["source"], "reason": reason})
            v["incomplete_sources"] = miss
            v["comparison_incomplete"] = bool(miss) or p["comparison_incomplete"]


def _report_slot_due(now, settings) -> tuple:
    """(due, slot_key): full periodic report due inside one of telegram_report_times (+grace)?"""
    times = settings.telegram_report_times or []
    if not times:
        return True, ""
    local = now.astimezone(settings.tz())
    for t in times:
        h, m = int(t.split(":")[0]), int(t.split(":")[1])
        slot = local.replace(hour=h, minute=m, second=0, microsecond=0)
        if slot <= local <= slot + timedelta(minutes=settings.telegram_report_grace_minutes):
            slot_key = slot.strftime("%Y-%m-%d %H:%M")
            state = history.load_state(settings.telegram_report_state_file)
            if state.get("last_slot") != slot_key:
                return True, slot_key
            return False, slot_key
    return False, ""


def _telegram_phase(settings, doc, products, current, alerts, run_at, now):
    """Full periodic report AND drop/opportunity alerts are two independent channels (V2 §7/§10)."""
    tok, chat = os.environ.get("TELEGRAM_BOT_TOKEN"), os.environ.get("TELEGRAM_CHAT_ID")
    statuses, exit_code = [], EXIT_OK
    alert_state = history.load_state(settings.telegram_alert_state_file)
    to_send = history.unsent_alerts(alerts, alert_state) if settings.telegram_alerts_enabled else []
    want_full, slot_key = _report_slot_due(now, settings)
    last_sent = history.load_state(settings.telegram_state_file)
    changed_map, removed = history.changed_keys(current, last_sent, settings.telegram_min_change_pct)
    changed = bool(changed_map or removed)
    full_allowed = want_full and not (settings.telegram_only_on_change and not changed and current)
    if not to_send and not full_allowed:
        if settings.telegram_report_times and not want_full:
            return (f"no scheduled slot now (report times: {', '.join(settings.telegram_report_times)}); "
                    f"alerts: 0 new"), EXIT_OK
        return f"no change >= {settings.telegram_min_change_pct}% since the last message: not sent", EXIT_OK
    if not (tok and chat):
        return "FAILED: TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID are not set", EXIT_TELEGRAM
    try:
        if to_send:
            msgs = report.build_alert_messages(to_send)
            log.info("telegram: sending %d alert message(s) ...", len(msgs))
            parts = telegram.send(tok, chat, msgs, settings.telegram_max_message_len,
                                  dry_run=settings.telegram_dry_run, max_messages=settings.telegram_max_messages)
            statuses.append(f"{len(parts)} alert message(s)" +
                            (" NOT sent (dry-run)" if settings.telegram_dry_run else " sent"))
            if not settings.telegram_dry_run:
                for a in to_send:
                    alert_state[history.alert_key(a)] = {"price": a.get("new_price"), "type": a.get("type"),
                                                         "run_at": run_at}
                history.save_state(settings.telegram_alert_state_file, alert_state)
        if full_allowed:
            msgs = report.build_telegram_messages(
                doc, settings.telegram_group_by, changed_map if settings.telegram_mode == "changes_only" else None,
                removed, settings.telegram_show_links)
            log.info("telegram: sending %d report message(s) ...", len(msgs))
            parts = telegram.send(tok, chat, msgs, settings.telegram_max_message_len,
                                  dry_run=settings.telegram_dry_run, max_messages=settings.telegram_max_messages)
            if settings.telegram_dry_run:
                statuses.append(f"dry-run: {len(parts)} message(s) NOT sent (telegram_dry_run=true)")
            else:
                history.save_state(settings.telegram_state_file, current)
                if slot_key:
                    history.save_state(settings.telegram_report_state_file, {"last_slot": slot_key})
                statuses.append(f"sent {len(parts)} message(s)")
    except Exception as exc:               # never leak the bot token (it is inside the request URL)
        return "FAILED: " + str(exc).replace(tok or "", "***"), EXIT_TELEGRAM
    return " | ".join(statuses) or "nothing to send", exit_code


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
