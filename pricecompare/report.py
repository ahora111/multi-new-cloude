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
                "offers_total", "offers_valid", "needs_review", "warnings",
                # V2 columns (appended: consumers of the old layout keep working)
                "canonical_title", "reference_price_toman", "winner_delivery", "fastest_source",
                "fastest_delivery", "price_change_percent", "comparison_incomplete"])
    from .pricing import reference_price
    for p in products:
        for v in p["variants"]:
            wn, ru, sv = v["winner"] or {}, v["runner_up"] or {}, v["savings"] or {}
            fastest = v.get("fastest") or {}
            w.writerow([p["id"], p.get("label") or p["model"], v["variant"], wn.get("source", ""), wn.get("price_toman", ""),
                        wn.get("url", ""), ru.get("source", ""), ru.get("price_toman", ""),
                        sv.get("amount_toman", ""), sv.get("percent", ""), len(v["offers"]),
                        sum(1 for o in v["offers"] if o["valid"]), v["needs_review"], " | ".join(v["warnings"]),
                        p.get("title") or p.get("label") or p["model"], reference_price(p) or "",
                        (wn.get("delivery_label") or "") if wn else "",
                        fastest.get("source", ""), fastest.get("delivery_label", ""),
                        v.get("price_change_pct", ""), "yes" if v.get("comparison_incomplete") else ""])
    return buf.getvalue()


def build_markdown(doc) -> str:
    from .pricing import reference_price
    L = [f"# گزارش مقایسه قیمت — {_tehran_stamp(doc)} (تومان)", ""]
    s = doc["summary"]
    L += [f"منابع سالم: {s['sources_ok']} | منابع خراب/مشکوک: {s['sources_failed'] + s['sources_degraded']} | "
          f"محصولات یافت‌شده: {s['products_found']}/{s['products_total']} | نیاز به بازبینی: {s['review_items']}", "",
          "ترتیب محصولات: از گران‌ترین به ارزان‌ترین (قیمت مرجع = ارزان‌ترین قیمت معتبر رنگ‌ها)", ""]
    if doc["warnings"]:
        L += ["## ⚠️ هشدارها"] + [f"- {w}" for w in doc["warnings"]] + [""]
    for p in doc["products"]:
        ref = reference_price(p)
        head = f"## {p.get('title') or p.get('label') or p['model']}"
        if ref is not None:
            head += f" — قیمت مرجع: {money(ref)}"
        L.append(head)
        if p.get("comparison_incomplete"):
            L.append("> ⚠️ مقایسه این محصول ناقص است (یک یا چند منبع در این چرخه در دسترس نبودند).")
        if p["status"] == "not_found":
            L += ["❌ در هیچ منبعی پیدا نشد.", ""]
            continue
        if p["status"] == "no_valid_price":
            L += ["⚠️ پیدا شد ولی پیشنهاد معتبر (موجود و با قیمت درست) وجود ندارد.", ""]
        for v in p["variants"]:
            L.append(f"### 🔹 {_color_display(v)}")
            for o in sorted([o for o in v["offers"]], key=lambda o: (not o["valid"], o["price_toman"] or 0)):
                if o["valid"] and not o["suspect"]:
                    mark = "✅" if v["winner"] and (o["source"], o["offer_id"]) == (v["winner"]["source"], v["winner"]["offer_id"]) else "▫️"
                    L.append(f"- {mark} {o['source']}: {money(o['price_toman'])}" + _age_suffix(o))
                elif o["suspect"]:
                    L.append(f"- ⚠️ {o['source']}: {money(o['price_toman'])} (مشکوک)")
                else:
                    L.append(f"- ✖️ {o['source']}: {money(o['price_toman'])} ({o['excluded_reason']})")
            for m in v.get("incomplete_sources") or []:
                L.append(f"- ✖️ {m['source']}: {m['reason']}")
            if v["winner"]:
                w = v["winner"]
                L.append(f"\n🏆 **{w['source']} — {money(w['price_toman'])}** ({v['why']})")
                if w.get("delivery_label"):
                    L.append(f"🚚 تحویل تقریبی: {w['delivery_label']} | {w.get('shipping_label') or 'هزینه ارسال نیازمند استعلام'}")
                L.append(f"🔗 {w['url'] or 'بدون لینک'}")
            else:
                L.append(f"\n⚠️ {v['why']}")
            fast = v.get("fastest")
            if fast:
                L.append(f"⚡ سریع‌ترین ارسال: {fast['source']} — {fast['delivery_label']}")
            for a in v.get("alerts") or []:
                L.append(_alert_line(a))
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


def _age_suffix(o) -> str:
    fa = o.get("fetched_at")
    if not fa:
        return ""
    try:
        from datetime import datetime
        dt = datetime.fromisoformat(fa)
        return f" (استخراج: {dt.strftime('%m-%d %H:%M')})"
    except (ValueError, TypeError):
        return ""


def write_all(outdir, doc, matching_report, run_summary):
    out = Path(outdir)
    atomic_write(out / "output.json", json.dumps(doc, ensure_ascii=False, indent=2))
    atomic_write(out / "report.csv", "\ufeff" + build_csv(doc["products"]))  # BOM: Excel reads Persian correctly
    atomic_write(out / "report.md", build_markdown(doc))
    atomic_write(out / "matching_report.json", json.dumps(matching_report, ensure_ascii=False, indent=2))
    atomic_write(out / "run_summary.json", json.dumps(run_summary, ensure_ascii=False, indent=2))


BRAND_TITLE = {"apple": "🍎 Apple", "samsung": "📱 Samsung", "xiaomi": "📱 Xiaomi", "google": "📱 Google", "nokia": "📱 Nokia",
               "honor": "📱 Honor", "tecno": "📱 Tecno", "other": "📱 سایر برندها"}

# ---- V2: one canonical title per product, ALL colours underneath it, every vendor priced per colour ----
COLOR_EMOJI = {"black": "⚫", "white": "⚪", "blue": "🔵", "green": "🟢", "red": "🔴", "yellow": "🟡",
               "orange": "🟠", "purple": "🟣", "pink": "🌸", "brown": "🟤", "gray": "🔘", "gold": "🟡",
               "silver": "⚪", "deep_blue": "🔵", "midnight": "⚫", "starlight": "⚪", "cream": "⚪",
               "mint": "🟢", "lime": "🟢", "lilac": "🟣", "phantom_black": "⚫", "titanium_black": "⚫",
               "titanium_gray": "🔘", "natural titanium": "🔘", "desert titanium": "🟤", "white titanium": "⚪"}

COLOR_FA = {"black": "مشکی", "white": "سفید", "blue": "آبی", "green": "سبز", "red": "قرمز", "yellow": "زرد",
            "orange": "نارنجی", "purple": "بنفش", "pink": "صورتی", "brown": "قهوه‌ای", "gray": "خاکستری",
            "gold": "طلایی", "silver": "نقره‌ای", "deep_blue": "سرمه‌ای", "midnight": "مشکی نیمه‌شب",
            "starlight": "استارلایت", "cream": "کرم", "mint": "نعنایی", "lime": "لیمویی", "lilac": "یاسی",
            "phantom_black": "مشکی فانتوم", "titanium_black": "تیتانیوم مشکی", "titanium_gray": "تیتانیوم خاکستری",
            "natural titanium": "تیتانیوم طبیعی", "desert titanium": "تیتانیوم صحرایی", "white titanium": "تیتانیوم سفید"}


def _color_display(v) -> str:
    """Canonical colour -> emoji + Persian name; non-colour variants keep their label."""
    color = (v.get("attributes") or {}).get("color") or v.get("canonical_color") or ""
    if color and color in COLOR_FA:
        return f"{COLOR_EMOJI.get(color, '🔹')} {COLOR_FA[color]}"
    return v.get("variant") or "بدون رنگ/مشخصه"


def _color_prefix_swap(line: str, v) -> str:
    """Replace the leading '🔹 <canonical-color>:' of a _line() result with the Persian colour
    display, keeping the rest of the line byte-identical (all vendor prices stay in place)."""
    color = (v.get("attributes") or {}).get("color") or ""
    if not color or color not in COLOR_FA:
        return line
    prefix = f"🔹 {v.get('variant')}:"
    if line.startswith(prefix):
        return f"{COLOR_EMOJI.get(color, '🔹')} {COLOR_FA[color]}:" + line[len(prefix):]
    return line


def _tehran_stamp(doc) -> str:
    gen = doc.get("generated_at") or ""
    tz_name = ((doc.get("cycle") or {}).get("timezone")) or "Asia/Tehran"
    try:
        from datetime import datetime
        from zoneinfo import ZoneInfo
        dt = datetime.fromisoformat(gen)
        return dt.astimezone(ZoneInfo(tz_name)).strftime("%Y-%m-%d %H:%M")
    except Exception:
        return gen[:16].replace("T", " ")


def _status_fa(s):
    return {"ok": "موفق", "degraded": "ناقص", "failed": "ناموفق", "stale": "داده قدیمی",
            "cached": "از کش"}.get(s.get("status"), s.get("status", ""))


def _alert_line(a) -> str:
    if a.get("type") == "vendor_drop":
        return (f"📉 فرصت خرید | کاهش {abs(a.get('percent') or 0):.0f}٪ | "
                f"{money(abs(a.get('amount_toman') or 0))} تومان ارزان‌تر — {a['source']}: "
                f"{money(a.get('prev_price'))} → {money(a.get('new_price'))}")
    if a.get("type") == "market_best":
        return (f"🏷️ بهترین قیمت بازار — {a['source']} {money(a.get('new_price'))} "
                f"({money(a.get('prev_price'))} → {money(a.get('new_price'))})")
    if a.get("type") == "vendor_increase":
        return (f"📈 افزایش قیمت {abs(a.get('percent') or 0):.0f}٪ — {a['source']}: "
                f"{money(a.get('prev_price'))} → {money(a.get('new_price'))}")
    return ""


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


def _v2_extra_lines(v, show_missing=False) -> list:
    """V2 per-colour lines: drop/opportunity alerts, fastest delivery. The per-source
    «قیمت دریافت نشد / منبع ناموفق» list is quiet by default (it made the channel noisy);
    the full per-offer detail stays in output.json / report.csv / report.md and can be
    re-enabled in Telegram with telegram_show_missing_sources: true."""
    out = []
    if show_missing:
        miss = v.get("incomplete_sources") or []
        if miss:
            out.append("   ⚠️ " + " | ".join(f"{m['source']}: {m['reason']}" for m in miss))
    for a in v.get("alerts") or []:
        al = _alert_line(a)
        if al:
            out.append("   " + al)
    fast = v.get("fastest")
    if fast:
        out.append(f"   🚚 سریع‌ترین ارسال: {fast['source']} — تحویل تقریبی {fast['delivery_label']} | "
                   f"{fast.get('shipping_label') or 'هزینه ارسال نیازمند استعلام'}")
    elif v.get("winner") and v.get("delivery_unknown"):
        out.append(f"   🚚 {_UNKNOWN_LABEL}")
    return out


_UNKNOWN_LABEL = "زمان تحویل نامشخص"


def build_telegram_messages(doc, group_by="brand", changes=None, removed=None, show_links=True,
                            show_missing_sources=False) -> list:
    """Plain-text posts (Telegram shows Markdown symbols literally). V2 layout: ONE canonical title
    per product; EVERY colour of the product listed underneath it; every vendor's price beside each
    colour; drop/opportunity alerts beside their colour; fastest delivery to Qazvin per colour.
    show_missing_sources=False (quiet default): sources without a price for a colour are NOT listed
    in the post — a colour the user asked to hide silently stays in the file outputs.
    changes: None = full report; dict(key -> old price|None) = only those variants (with the old price)."""
    from . import history
    products = doc["products"]            # already sorted most-expensive -> cheapest by the pipeline
    noisy = _link_noise(products)
    head = [f"📊 مقایسه قیمت — {_tehran_stamp(doc)} (تهران)",
            "منابع: " + " | ".join(f"{x['name']} {'✅' if x['status'] == 'ok' else '⚠️'} {_status_fa(x)}"
                                   for x in doc["sources"])]
    head += [f"⚠️ {x['name']}: {x['error']}" for x in doc["sources"] if x["status"] != "ok"]
    blocks = []                                          # (brand, product label, text)
    n_lines = 0
    for p in products:
        lines = []
        has_winner = any(v["winner"] for v in p["variants"])
        if changes is None and has_winner and p.get("comparison_incomplete") and show_missing_sources:
            lines.append("⚠️ مقایسه ناقص — یک یا چند منبع در دسترس نبودند")
        for v in p["variants"]:
            if not v["winner"]:
                # quiet default: a colour with no valid price is skipped in the post (kept in the files);
                # with show_missing_sources it is stated transparently instead of hidden
                if changes is None and has_winner and show_missing_sources:
                    lines.append(f"{_color_prefix_swap('🔹 ' + (v['variant'] or '') + ':', v)} قیمت معتبر ندارد ⚠️")
                continue
            key = history.key(p["id"], v["variant"])
            if changes is not None and key not in changes:
                continue
            base = _color_prefix_swap(_line(v, key, changes, None, show_links, noisy), v)
            lines.append(base)
            if changes is None:
                lines.extend(_v2_extra_lines(v, show_missing_sources))
        if lines:
            n_lines += len(lines)
            blocks.append((p["brand"], f"📱 {p.get('title') or p.get('label') or p['model']}\n" + "\n".join(lines)))
    if changes is None:
        head.append(f"{len(blocks)} محصول | مرتب‌شده از گران‌ترین به ارزان‌ترین — ارزان‌ترین قیمت هر رنگ")
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
    if changes is None and doc.get("price_changes"):
        top = [c for c in doc["price_changes"] if c.get("type") in ("vendor_drop", "market_best")]
        if top:
            msgs.append("📉 فرصت‌های خرید این چرخه:\n" + "\n".join(
                f"- {c['product_title']} / {c['variant']} — {_alert_line(c)}" for c in top[:10]))
    extra = [w for w in doc["warnings"] if not w.startswith("منبع")]
    if extra:
        msgs.append("⚠️ هشدارها:\n" + "\n".join(f"- {w}" for w in extra[:8]))
    return msgs


def build_alert_messages(alerts) -> list:
    """Independent short posts for drop/opportunity alerts (sent even when the full report is not due)."""
    groups = {}
    for a in alerts:
        groups.setdefault((a.get("product_id"), a.get("product_title")), []).append(a)
    msgs = []
    for (_, title), rows in groups.items():
        lines = [f"📱 {title}"]
        seen = set()
        for a in rows:
            vkey = (a.get("variant"), a.get("source"), a.get("new_price"))
            if vkey in seen:
                continue
            seen.add(vkey)
            color = COLOR_FA.get(a.get("variant") or "", a.get("variant") or "")
            lines.append(f"{COLOR_EMOJI.get(a.get('variant') or '', '🔹')} {color}: {_alert_line(a)}")
        msgs.append("\n".join(lines))
    return msgs


def build_telegram(doc) -> str:
    return "\n\n".join(build_telegram_messages(doc, "none")) + "\n"
