import csv
import io
import json
import os
from pathlib import Path
from . import SCHEMA_VERSION


def atomic_write(path, text):
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_name(p.name + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    os.replace(tmp, p)


def money(v):
    return f"{v:,.0f}" if v is not None else "—"


def build_document(run_at, products, not_found, review_queue, sources_status, warnings):
    return {"schema_version": SCHEMA_VERSION, "generated_at": run_at, "currency": "toman",
            "products": products, "not_found": not_found, "review_queue": review_queue,
            "sources": sources_status, "warnings": warnings}


def build_csv(products) -> str:
    buf = io.StringIO()
    w = csv.writer(buf, lineterminator="\n")
    w.writerow(["product_id", "model", "variant", "winner_source", "winner_price_toman", "winner_url",
                "runner_up_source", "runner_up_price_toman", "savings_toman", "savings_percent",
                "offers_total", "offers_valid", "needs_review", "warnings"])
    for p in products:
        for v in p["variants"]:
            wn, ru, sv = v["winner"] or {}, v["runner_up"] or {}, v["savings"] or {}
            w.writerow([p["id"], p["model"], v["variant"], wn.get("source", ""), wn.get("price_toman", ""),
                        wn.get("url", ""), ru.get("source", ""), ru.get("price_toman", ""),
                        sv.get("amount_toman", ""), sv.get("percent", ""), len(v["offers"]),
                        sum(1 for o in v["offers"] if o["valid"]), v["needs_review"], " | ".join(v["warnings"])])
    return buf.getvalue()


def build_markdown(doc) -> str:
    L = [f"# گزارش مقایسه قیمت — {doc['generated_at'][:16].replace('T', ' ')} (تومان)", ""]
    s = doc["summary"]
    L += [f"منابع سالم: {s['sources_ok']} | منابع خراب/مشکوک: {s['sources_failed'] + s['sources_degraded']} | "
          f"محصولات یافت‌شده: {s['products_found']}/{s['products_total']} | نیاز به بازبینی: {s['review_items']}", ""]
    if doc["warnings"]:
        L += ["## ⚠️ هشدارها"] + [f"- {w}" for w in doc["warnings"]] + [""]
    for p in doc["products"]:
        L.append(f"## {p['model']}" + (f" — {p['storage_gb']}GB" if p["storage_gb"] else ""))
        if p["status"] == "not_found":
            L += ["❌ در هیچ منبعی پیدا نشد.", ""]
            continue
        if p["status"] == "no_valid_price":
            L += ["⚠️ پیدا شد ولی پیشنهاد معتبر (موجود و با قیمت درست) وجود ندارد.", ""]
        for v in p["variants"]:
            L.append(f"### 🔹 {v['variant']}")
            for o in sorted([o for o in v["offers"]], key=lambda o: (not o["valid"], o["price_toman"] or 0)):
                if o["valid"] and not o["suspect"]:
                    mark = "✅" if v["winner"] and (o["source"], o["offer_id"]) == (v["winner"]["source"], v["winner"]["offer_id"]) else "▫️"
                    L.append(f"- {mark} {o['source']}: {money(o['price_toman'])}")
                elif o["suspect"]:
                    L.append(f"- ⚠️ {o['source']}: {money(o['price_toman'])} (مشکوک)")
                else:
                    L.append(f"- ✖️ {o['source']}: {money(o['price_toman'])} ({o['excluded_reason']})")
            if v["winner"]:
                w = v["winner"]
                L.append(f"\n🏆 **{w['source']} — {money(w['price_toman'])}** ({v['why']})")
                L.append(f"🔗 {w['url'] or 'بدون لینک'}")
            else:
                L.append(f"\n⚠️ {v['why']}")
            for x in v["warnings"]:
                L.append(f"⚠️ {x}")
            if v["needs_review"]:
                L.append("🔎 نیاز به بازبینی دستی")
            L.append("")
    if doc["not_found"]:
        L += ["## ❌ پیدا نشد"] + [f"- {x}" for x in doc["not_found"]] + [""]
    if doc["review_queue"]:
        L += ["## 🔎 صف بازبینی تطبیق (در قیمت‌گذاری وارد نشده‌اند)"]
        for r in doc["review_queue"]:
            L.append(f"- [{r['source']}] {r['title']} → {r['watch_id']} ({'; '.join(r['reasons'])})")
    return "\n".join(L) + "\n"


def write_all(outdir, doc, matching_report, run_summary):
    out = Path(outdir)
    atomic_write(out / "output.json", json.dumps(doc, ensure_ascii=False, indent=2))
    atomic_write(out / "report.csv", "\ufeff" + build_csv(doc["products"]))  # BOM: Excel reads Persian correctly
    atomic_write(out / "report.md", build_markdown(doc))
    atomic_write(out / "matching_report.json", json.dumps(matching_report, ensure_ascii=False, indent=2))
    atomic_write(out / "run_summary.json", json.dumps(run_summary, ensure_ascii=False, indent=2))
