import json
from pathlib import Path


<<<<<<< HEAD
=======
<<<<<<< HEAD
>>>>>>> origin/main
def _num(v):
    return int(v) if isinstance(v, float) and v.is_integer() else v


<<<<<<< HEAD
=======
=======
>>>>>>> f17e6a59f11b4c55f7e0c722244e8621d106d9dc
>>>>>>> origin/main
def key(product_id, variant):
    return f"{product_id}|{variant}"


<<<<<<< HEAD
=======
<<<<<<< HEAD
>>>>>>> origin/main
def alert_key(entry) -> str:
    """Dedup identity of an alert: same (type, product, colour, vendor) at the same price = no repost."""
    return f'{entry.get("type")}|{entry.get("product_id")}|{entry.get("variant")}|{entry.get("source")}'


def _per_source_prices(variant, run_at) -> dict:
    """Lowest VALID, non-suspect price per vendor for one variant/colour. Suspect or invalid
    prices are never recorded, so they can never become a % baseline later."""
    per = {}
    for o in variant.get("offers", []):
        if not (o.get("valid") and not o.get("suspect") and o.get("price_toman")):
            continue
        s = o["source"]
        cur = per.get(s)
        if cur is None or o["price_toman"] < cur["price"]:
            per[s] = {"price": _num(o["price_toman"]), "recorded_at": run_at,
                      "fetched_at": o.get("fetched_at") or ""}
    return per


def last_record(path) -> dict | None:
    """Whole last history line (run_at + prices + source_prices) or None."""
    p = Path(path)
    if not p.exists():
        return None
<<<<<<< HEAD
=======
=======
def last_prices(path) -> dict:
    p = Path(path)
    if not p.exists():
        return {}
>>>>>>> f17e6a59f11b4c55f7e0c722244e8621d106d9dc
>>>>>>> origin/main
    last = None
    for line in p.read_text(encoding="utf-8").splitlines():
        if line.strip():
            last = line
<<<<<<< HEAD
=======
<<<<<<< HEAD
>>>>>>> origin/main
    return json.loads(last) if last else None


def last_prices(path) -> dict:
    rec = last_record(path)
    return (rec or {}).get("prices") or {}
<<<<<<< HEAD
=======
=======
    return json.loads(last)["prices"] if last else {}
>>>>>>> f17e6a59f11b4c55f7e0c722244e8621d106d9dc
>>>>>>> origin/main


def price_changes(products, previous, alert_pct):
    """Annotate variants with a warning if the winner moved > alert_pct vs the previous run."""
    alerts = []
    for p in products:
        for v in p["variants"]:
            prev = previous.get(key(p["id"], v["variant"]))
            if v["winner"] and prev and prev.get("price"):
                change = (v["winner"]["price_toman"] - prev["price"]) / prev["price"] * 100
                v["price_change_pct"] = round(change, 2)
                if abs(change) > alert_pct:
                    msg = f"تغییر قیمت {change:+.1f}٪ نسبت به اجرای قبل"
                    v["warnings"].append(msg)
                    alerts.append(f"{p['id']} / {v['variant']}: {msg}")
    return alerts


<<<<<<< HEAD
=======
<<<<<<< HEAD
>>>>>>> origin/main
def detect_changes(products, prev_record, drop_pct: float, market_pct: float, now_iso: str,
                   max_age_hours: int = 48) -> list:
    """Per-product / per-colour / per-VENDOR price tracking (V2).

    Two independent states per colour:
      vendor_drop     — a vendor's own current valid price fell >= drop_pct below its own previous
                        valid price (the «فرصت خرید» alert). Increases >= drop_pct are recorded too.
      market_best     — a vendor's current price is STRICTLY lower than every other vendor's price
                        for the same exact product+colour AND undercuts the previous market lowest
                        by >= market_pct.

    Rules enforced here:
      - only valid, non-suspect prices participate (stale/invalid never becomes a baseline);
      - a baseline older than max_age_hours is discarded (re-registered, no % computed across it);
      - a colour/vendor without history gets type=base_registered («قیمت پایه در حال ثبت»), no alert;
      - EVERY detected change is returned (even below the alert threshold) so the cycle output
        keeps the full information — the `alert` flag only decides telegram delivery.
    """
    changes = []
    prev_run_at = (prev_record or {}).get("run_at")
    prev_too_old = False
    if prev_run_at:
        try:
            from datetime import datetime
            age_h = (datetime.fromisoformat(now_iso) - datetime.fromisoformat(prev_run_at)).total_seconds() / 3600
            prev_too_old = age_h > max_age_hours
        except (ValueError, TypeError):
            prev_too_old = False
    for p in products:
        for v in p["variants"]:
            k = key(p["id"], v["variant"])
            per_source = _per_source_prices({"offers": v.get("offers", [])}, now_iso)
            cur = {s: x["price"] for s, x in per_source.items()}
            prev_src = ((prev_record or {}).get("source_prices") or {}).get(k) or {}
            if prev_too_old:
                prev_src = {}                      # too old to be a trustworthy baseline
            prev_lowest = min((x["price"] for x in prev_src.values() if x.get("price")), default=None)
            lowest_now = min(cur.values(), default=None)
            for s, price in sorted(cur.items()):
                pb = prev_src.get(s) or {}
                entry = {"product_id": p["id"], "product_title": p.get("title") or p.get("label") or p.get("model") or p["id"],
                         "variant": v["variant"], "source": s,
                         "new_price": _num(price), "prev_price": _num(pb.get("price")) if pb.get("price") else None,
                         "prev_recorded_at": pb.get("recorded_at"), "recorded_at": now_iso,
                         "type": None, "alert": False, "amount_toman": None, "percent": None}
                if pb.get("price"):
                    amount = price - pb["price"]
                    pct = amount / pb["price"] * 100
                    entry.update(amount_toman=_num(amount), percent=round(pct, 2))
                    if pct <= -abs(drop_pct) and drop_pct >= 0 and pct < 0:
                        entry["type"] = "vendor_drop"
                        entry["alert"] = True
                    elif drop_pct >= 0 and pct >= drop_pct and pct > 0:
                        entry["type"] = "vendor_increase"
                else:
                    entry["type"] = "base_registered"
                    entry["note"] = "قیمت پایه در حال ثبت"
                # best-market-price: this vendor is NOW strictly the lowest of the exact product+colour
                strictly_lowest = (lowest_now is not None and price == lowest_now
                                   and all(price < x for xs, x in cur.items() if xs != s))
                if strictly_lowest and prev_lowest is not None and price < prev_lowest:
                    beat = (prev_lowest - price) / prev_lowest * 100
                    if market_pct <= 0 or beat >= market_pct:
                        if entry["type"] is None:
                            entry["type"] = "market_best"
                            entry["alert"] = True
                        else:
                            entry["also_market_best"] = True
                changes.append(entry)
    return changes


def append(path, products, run_at):
    prices = {key(p["id"], v["variant"]): {"price": v["winner"]["price_toman"], "source": v["winner"]["source"]}
              for p in products for v in p["variants"] if v["winner"]}
    source_prices = {key(p["id"], v["variant"]): _per_source_prices(v, run_at)
                     for p in products for v in p["variants"]}
    source_prices = {k: v for k, v in source_prices.items() if v}
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    with open(path, "a", encoding="utf-8") as f:
        f.write(json.dumps({"run_at": run_at, "prices": prices, "source_prices": source_prices},
                           ensure_ascii=False) + "\n")


def append_alerts(path, changes, run_at) -> int:
    """Persistent alert/change log (append-only). Stores EVERY change with a type, even below the
    telegram threshold — the cycle output and the alert dedup state both rely on it."""
    rows = [c for c in changes or [] if c.get("type")]
    if not rows:
        return 0
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    with open(p, "a", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps({"run_at": run_at, **r}, ensure_ascii=False) + "\n")
    return len(rows)
<<<<<<< HEAD
=======
=======
def append(path, products, run_at):
    prices = {key(p["id"], v["variant"]): {"price": v["winner"]["price_toman"], "source": v["winner"]["source"]}
              for p in products for v in p["variants"] if v["winner"]}
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    with open(path, "a", encoding="utf-8") as f:
        f.write(json.dumps({"run_at": run_at, "prices": prices}, ensure_ascii=False) + "\n")
>>>>>>> f17e6a59f11b4c55f7e0c722244e8621d106d9dc
>>>>>>> origin/main


def load_state(path) -> dict:
    p = Path(path)
    try:
        return json.loads(p.read_text(encoding="utf-8")) if p.exists() else {}
    except (OSError, ValueError):
        return {}


def save_state(path, prices) -> None:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_name(p.name + ".tmp")
    tmp.write_text(json.dumps(prices, ensure_ascii=False, indent=1), encoding="utf-8")
    tmp.replace(p)


def changed_keys(current: dict, last_sent: dict, min_pct: float):
    """(changed, removed): changed = {key: previous_price or None (new)} for variants whose winner price moved by
    >= min_pct % (or that appeared); removed = keys that had a winner in the last message but not now.
    A change of the winning SOURCE alone (same price) is not a change: shops swap the lead by a few toman all day."""
    changed = {}
    for k, cur in current.items():
        if k not in last_sent:
            changed[k] = None
            continue
        old = last_sent[k].get("price") or 0
        if old <= 0 or (cur["price"] != old and abs(cur["price"] - old) / old * 100 >= min_pct):
            changed[k] = old or None
    removed = [k for k in last_sent if k not in current]
    return changed, removed


def significant_change(current: dict, last_sent: dict, min_pct: float) -> bool:
    changed, removed = changed_keys(current, last_sent, min_pct)
    return bool(changed or removed)
<<<<<<< HEAD
=======
<<<<<<< HEAD
>>>>>>> origin/main


def unsent_alerts(alerts: list, alert_state: dict) -> list:
    """Alerts whose (type, product, colour, vendor) was not already sent at the SAME new price."""
    out = []
    for a in alerts:
        prev = alert_state.get(alert_key(a))
        if not prev or prev.get("price") != a.get("new_price"):
            out.append(a)
    return out
<<<<<<< HEAD
=======
=======
>>>>>>> f17e6a59f11b4c55f7e0c722244e8621d106d9dc
>>>>>>> origin/main
