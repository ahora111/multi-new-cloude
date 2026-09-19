from __future__ import annotations
import argparse
import json
import logging
import os
import re
import sys
from pathlib import Path
from .runner import run, EXIT_OK


def load_dotenv(path=".env") -> int:
    """Minimal .env reader (KEY=VALUE). Existing environment variables always win. Values are never logged."""
    p = Path(path)
    if not p.exists():
        return 0
    n = 0
    for line in p.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, _, v = line.partition("=")
        k, v = k.strip(), v.strip().strip('"').strip("'")
        if k and v and k not in os.environ:
            os.environ[k] = v
            n += 1
    return n


def _print_summary(res, show_offers=0, print_report=False):
    s = res.summary
    if not s:
        return
    keys = ["sources_ok", "sources_failed", "sources_degraded", "offers_total", "products_total",
            "products_found", "products_not_found", "review_items", "suspect_offers", "needs_review_variants"]
    print("\n".join(f"{k}: {s[k]}" for k in keys if k in s))
    for st in s.get("sources", []):
        cat = f", catalog={st['catalog_count']}" if "catalog_count" in st else ""
        print(f"  - {st['name']}: {st['status']} ({st['count']} relevant offers{cat}, {st['seconds']}s)" +
              (f" — {st['error']}" if st.get("error") else ""))
    if "telegram" in s:
        print(f"telegram: {s['telegram']}")
    if res.doc:
        print("\nresults:")
        for p in res.doc["products"]:
            if p["status"] == "not_found":
                print(f"  ✗ {p['id']}: not found in any source")
                continue
            for v in p["variants"]:
                w = v["winner"]
                print(f"  {'✓' if w else '✗'} {p['id']} [{v['variant']}]: " +
                      (f"{w['source']} {w['price_toman']:,.0f}" if w else v["why"]) +
                      ("  ⚠ review" if v["needs_review"] else ""))
    if res.match_report:
        from collections import Counter
        st = Counter(r["status"] for r in res.match_report)
        print("\nmatching: " + " | ".join(f"{k}={v}" for k, v in sorted(st.items())))
        why = Counter(re.sub(r"\(.*?\)|[0-9.]+", "", re.sub(r"^nearest=\S+:\s*", "", r["reasons"][0])).strip()[:60]
                      for r in res.match_report if r["status"] == "NO_MATCH" and r["reasons"])
        if why:
            print("top rejection reasons: " + "; ".join(f"{k} ×{n}" for k, n in why.most_common(5)))
    if show_offers and res.offers:
        from .matcher import best_result
        print(f"\nsample offers per source (closest to your watchlist first, {show_offers} each):")
        for src in sorted({o.source for o in res.offers}):
            rows = [(best_result(o, res.watchlist, res.watch_attrs, res.settings), o) for o in res.offers if o.source == src]
            rows.sort(key=lambda ro: ({"AUTO_MATCH": 2, "REVIEW": 1, "NO_MATCH": 0}[ro[0].status],
                                       len(set(res.watch_attrs[ro[0].watch_id].core) & set(ro[1].model_core)), ro[0].score), reverse=True)
            print(f"--- {src}")
            for r_, o in rows[:show_offers]:
                print(f"  {o.raw_title[:70]!r} price={o.price_toman and int(o.price_toman):,} | brand={o.brand or '?'} core={' '.join(o.model_core)} "
                      f"tiers={o.tiers} {o.storage_gb}GB ram={o.ram_gb} color={o.color or '?'}\n"
                      f"      -> {r_.watch_id}: {r_.status} ({'; '.join(r_.reasons)})")
    if print_report and res.doc:
        from .report import build_markdown
        print("\n" + build_markdown(res.doc))


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="pricecompare", description="Multi-source price comparison")
    ap.add_argument("--config-dir", default="config")
    ap.add_argument("--base-dir", default=".", help="base for relative source paths")
    ap.add_argument("--log-level", default="INFO")
    sub = ap.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("run", help="fetch, match, price, write outputs")
    r.add_argument("--dry-run", action="store_true", help="do everything but write files / send messages")
    r.add_argument("--only-source")
    r.add_argument("--require-all-sources", action="store_true")
    r.add_argument("--output-dir")
    r.add_argument("--no-telegram", action="store_true", help="never send Telegram messages in this run")
    r.add_argument("--show-offers", type=int, default=0, metavar="N", help="print N sample offers per source with how they matched")
    r.add_argument("--print-report", action="store_true", help="print the Persian report to the console/log")
    sub.add_parser("check-sources", help="fetch every source and report health")
    m = sub.add_parser("match-report", help="show how offers were matched/rejected in the last run")
    m.add_argument("--status", choices=["AUTO_MATCH", "REVIEW", "NO_MATCH", "FORCED_SPLIT"])
    m.add_argument("--output-dir", default=None)
    e = sub.add_parser("explain", help="explain the last result for a watchlist product id")
    e.add_argument("product_id")
    e.add_argument("--output-dir", default=None)
    a = ap.parse_args(argv)
    load_dotenv()
    logging.basicConfig(level=a.log_level.upper(), format="%(asctime)s | %(levelname)s | %(name)s | %(message)s")

    if a.cmd == "run":
        res = run(a.config_dir, a.output_dir, a.dry_run, a.only_source, a.require_all_sources, a.base_dir,
                  send_telegram=not a.no_telegram)
        _print_summary(res, a.show_offers, a.print_report)
        if res.exit_code != EXIT_OK:
            print(res.message, file=sys.stderr)
        return res.exit_code
    if a.cmd == "check-sources":
        res = run(a.config_dir, dry_run=True, base_dir=a.base_dir)
        _print_summary(res)
        return 0 if res.summary.get("sources_failed", 1) == 0 and res.summary.get("sources_degraded", 1) == 0 else 1
    from .config import load_settings, ConfigError
    try:
        outdir = Path(a.output_dir or load_settings(a.config_dir).output_dir)
    except ConfigError as exc:
        print(f"config error: {exc}", file=sys.stderr); return 4
    if a.cmd == "match-report":
        rows = json.loads((outdir / "matching_report.json").read_text(encoding="utf-8"))
        for r_ in rows:
            if a.status and r_["status"] != a.status:
                continue
            print(f"[{r_['status']:<12}] {r_['score']:>6}  {r_['source']}: {r_['title']}\n"
                  f"     -> {r_['watch_id'] or '-'} | {'; '.join(r_['reasons'])}")
        return 0
    if a.cmd == "explain":
        doc = json.loads((outdir / "output.json").read_text(encoding="utf-8"))
        prod = next((p for p in doc["products"] if p["id"] == a.product_id), None)
        if not prod:
            print(f"unknown product id {a.product_id!r}", file=sys.stderr); return 1
        print(f"{prod['model']} — status: {prod['status']}")
        for v in prod["variants"]:
            print(f"\n[{v['variant']}] {v['why']}")
            for o in v["offers"]:
                flag = "VALID " if o["valid"] and not o["suspect"] else ("SUSPECT" if o["suspect"] else "EXCL  ")
                print(f"   {flag} {o['source']:<12} {o['price_toman'] or 0:>14,.0f}  {o['excluded_reason'] or ''}  | {o['title']}")
            for w in v["warnings"]:
                print(f"   ! {w}")
        rows = json.loads((outdir / "matching_report.json").read_text(encoding="utf-8"))
        near = [r_ for r_ in rows if r_["status"] == "NO_MATCH" and prod["id"] in " ".join(r_["reasons"])]
        if near:
            print("\nNearest rejected offers:")
            for r_ in near[:10]:
                print(f"   {r_['source']}: {r_['title']}  -> {'; '.join(r_['reasons'])}")
        return 0
    return 0


if __name__ == "__main__":
    sys.exit(main())
