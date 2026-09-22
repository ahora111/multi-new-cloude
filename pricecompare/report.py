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
            w.writerow([p["id"], p.get("label") or p["model"], v["variant"], wn.get("source", ""), wn.get("price_toman", ""),
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
        L.append(f"## {p.get('label') or p['model']}")
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


BRAND_TITLE = {"apple": "🍎 Apple", "samsung": "📱 Samsung", "xiaomi": "📱 Xiaomi", "google": "📱 Google", "nokia": "📱 Nokia",
               "honor": "📱 Honor", "tecno": "📱 Tecno", "other": "📱 سایر برندها"}


def _link_noise(products) -> set:
    """Winner URLs shared by 3+ lines (e.g. one category page for a whole shop) carry no information: never print them."""
    from collections import Counter
    c = Counter(v["winner"]["url"] for p in products for v in p["variants"] if v["winner"] and v["winner"]["url"])
    return {u for u, n in c.items() if n >= 3}


def _line(v, key, changes, last_sent, show_links, noisy):
    w, r = v["winner"], v["runner_up"]
    line = f"🔹 {v['variant']}: 🏆 {w['source']} {money(w['price_toman'])}"
    if v.get("single_source"):
        line += " (تک‌منبع)"
    else:
        # Telegram should show every valid source for the variant, not only
        # winner + runner-up. The detailed report already keeps all offers;
        # this makes the concise Telegram view consistent with it.
        offers = [
            o for o in v.get("offers", [])
            if o.get("valid") and not o.get("suspect") and o.get("price_toman") is not None
        ]
        # Keep one offer per source (lowest valid price), while keeping the
        # winner first even if the internal offer order changes.
        by_source = {}
        for o in offers:
            prev = by_source.get(o["source"])
            if prev is None or o["price_toman"] < prev["price_toman"]:
                by_source[o["source"]] = o
        winner_key = (w.get("source"), w.get("offer_id"))
        others = [
            o for o in by_source.values()
            if (o.get("source"), o.get("offer_id")) != winner_key
        ]
        others.sort(key=lambda o: (o["price_toman"], o["source"]))
        for o in others:
            line += f" | {o['source']} {money(o['price_toman'])}"
    if changes is not None and key in changes:
        old = changes[key]
        line += " 🆕" if old is None else f" ({'▼' if w['price_toman'] < old else '▲'} قبلاً {money(old)})"
    if v["needs_review"] or v["warnings"]:
        line += " ⚠️"
    if show_links and w["url"] and w["url"] not in noisy:
        line += f"\n   🔗 {w['url']}"
    return line


def build_telegram_messages(doc, group_by="brand", changes=None, removed=None, show_links=True) -> list:
    """Plain-text posts (Telegram shows Markdown symbols literally). Cheapest valid price PER COLOUR for every phone.
    changes: None = full report; dict(key -> old price|None) = only those variants (with the old price)."""
    from . import history
    products = sorted(doc["products"], key=lambda p: (p["brand"], p.get("label") or p["model"]))
    noisy = _link_noise(products)
    head = [f"📊 مقایسه قیمت — {doc['generated_at'][:16].replace('T', ' ')} UTC",
            "منابع: " + " | ".join(f"{x['name']} {'✅' if x['status'] == 'ok' else '⚠️'}" for x in doc["sources"])]
    head += [f"⚠️ {x['name']}: {x['error']}" for x in doc["sources"] if x["status"] != "ok"]
    blocks = []                                          # (brand, product label, text)
    n_lines = 0
    for p in products:
        lines = []
        for v in p["variants"]:
            if not v["winner"]:
                continue
            key = history.key(p["id"], v["variant"])
            if changes is not None and key not in changes:
                continue
            lines.append(_line(v, key, changes, None, show_links, noisy))
        if lines:
            n_lines += len(lines)
            blocks.append((p["brand"], f"📱 {p.get('label') or p['model']}\n" + "\n".join(lines)))
    if changes is None:
        head.append(f"{len(blocks)} محصول | {n_lines} رنگ/واریانت — ارزان‌ترین قیمت هر رنگ")
    else:
        head.append(f"فقط تغییرات از آخرین پیام: {n_lines} مورد" + (f" | {len(removed or [])} مورد دیگر پیشنهاد معتبر ندارد" if removed else ""))
    msgs = ["\n".join(head)]
    if not blocks:
        msgs.append("پیشنهاد معتبری برای نمایش نیست.")
    elif group_by == "product":
        msgs += [b[1] for b in blocks]
    elif group_by == "none":
        msgs.append("\n\n".join(b[1] for b in blocks))
    else:
        groups = {}
        for brand, text in blocks:
            groups.setdefault(brand, []).append(text)
        for brand, texts in groups.items():
            msgs.append(f"━━ {BRAND_TITLE.get(brand, '📱 ' + brand.capitalize())} ━━\n\n" + "\n\n".join(texts))
    if changes is None and doc["not_found"]:
        msgs.append("❌ در هیچ منبعی پیدا نشد: " + "، ".join(doc["not_found"]))
    extra = [w for w in doc["warnings"] if not w.startswith("منبع")]
    if extra:
        msgs.append("⚠️ هشدارها:\n" + "\n".join(f"- {w}" for w in extra[:8]))
    return msgs


def build_telegram(doc) -> str:
    return "\n\n".join(build_telegram_messages(doc, "none")) + "\n"


def write_all(outdir, doc, matching_report, run_summary):
    out = Path(outdir)
    atomic_write(out / "output.json", json.dumps(doc, ensure_ascii=False, indent=2))
    atomic_write(out / "report.csv", "\ufeff" + build_csv(doc["products"]))  # BOM: Excel reads Persian correctly
    atomic_write(out / "report.md", build_markdown(doc))
    atomic_write(out / "matching_report.json", json.dumps(matching_report, ensure_ascii=False, indent=2))
    atomic_write(out / "run_summary.json", json.dumps(run_summary, ensure_ascii=False, indent=2))


def build_telegram(doc) -> str:
    """Compact plain text (no Markdown symbols, Telegram shows them literally)."""
    L = [f"📊 مقایسه قیمت — {doc['generated_at'][:16].replace('T', ' ')} UTC"]
    bad = [x for x in doc["sources"] if x["status"] != "ok"]
    L.append("منابع: " + " | ".join(f"{x['name']} {'✅' if x['status'] == 'ok' else '⚠️'}" for x in doc["sources"]))
    for x in bad:
        L.append(f"⚠️ {x['name']}: {x['error']}")
    L.append("")
    for p in doc["products"]:
        if p["status"] == "not_found":
            continue
        L.append(f"📱 {p['model']}" + (f" {p['storage_gb']}GB" if p["storage_gb"] else ""))
        for v in p["variants"]:
            w, r = v["winner"], v["runner_up"]
            if not w:
                L.append(f"🔹 {v['variant']}: بدون پیشنهاد معتبر")
                continue
            flag = " ⚠️" if v["needs_review"] or v["warnings"] else ""
            L.append(f"🔹 {v['variant']}: 🏆 {w['source']} {money(w['price_toman'])}{flag}")
            if r:
                L.append(f"   بعدی: {r['source']} {money(r['price_toman'])}")
            L.append(f"   🔗 {w['url'] or 'بدون لینک'}")
        L.append("")
    if doc["not_found"]:
        L.append("❌ پیدا نشد: " + "، ".join(doc["not_found"]))
    extra = [w for w in doc["warnings"] if not w.startswith("منبع")]
    if extra:
        L += ["", "⚠️ هشدارها:"] + [f"- {w}" for w in extra[:8]]
    return "\n".join(L).strip() + "\n"
