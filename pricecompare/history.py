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
