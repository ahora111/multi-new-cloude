import json
from pathlib import Path


def key(product_id, variant):
    return f"{product_id}|{variant}"


def last_prices(path) -> dict:
    p = Path(path)
    if not p.exists():
        return {}
    last = None
    for line in p.read_text(encoding="utf-8").splitlines():
        if line.strip():
            last = line
    return json.loads(last)["prices"] if last else {}


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


def append(path, products, run_at):
    prices = {key(p["id"], v["variant"]): {"price": v["winner"]["price_toman"], "source": v["winner"]["source"]}
              for p in products for v in p["variants"] if v["winner"]}
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    with open(path, "a", encoding="utf-8") as f:
        f.write(json.dumps({"run_at": run_at, "prices": prices}, ensure_ascii=False) + "\n")


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
