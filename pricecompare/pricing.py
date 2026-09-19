"""Per-variant lowest valid price with two-sided outlier control and explanations."""
from __future__ import annotations
from datetime import datetime, timezone
from itertools import combinations
from statistics import median
from .models import IN_STOCK


def variant_parts(off, watch) -> dict:
    parts = {"color": off.color}
    if watch.storage_gb is None:
        parts["storage_gb"] = off.storage_gb
    if watch.ram_gb is None:
        parts["ram_gb"] = off.ram_gb
    # region / activation are NOT part of the key: many shops omit them, which would split one
    # product into fake variants. Mixed known values are flagged instead (see build_product).
    return parts


def variant_label(parts: dict) -> str:
    out = []
    for k, v in parts.items():
        if v in (None, ""):
            continue
        out.append(f"{v}GB" if k == "storage_gb" else f"RAM {v}GB" if k == "ram_gb" else str(v))
    return " / ".join(out) or "بدون رنگ/مشخصه"


def invalid_reason(off, now, settings, degraded):
    if off.price_toman is None or off.price_toman <= 0:
        return "قیمت نامعتبر"
    if off.stock != IN_STOCK:
        return "ناموجود یا نامشخص"
    if off.fetched_at:
        try:
            age = (now - datetime.fromisoformat(off.fetched_at)).total_seconds() / 60
            if age > settings.max_price_age_minutes:
                return "قیمت قدیمی"
        except ValueError:
            pass
    if off.source in degraded:
        return "منبع مشکوک (کمتر از حداقل محصولات)"
    return None


def _num(v):
    return int(v) if isinstance(v, float) and v.is_integer() else v


def _offer_dict(off, reason, suspect):
    return {"source": off.source, "offer_id": off.source_offer_id, "title": off.raw_title,
            "color": off.color, "price_raw": _num(off.price_raw), "currency_unit_raw": off.currency_unit_raw,
            "price_toman": _num(off.price_toman), "stock": off.stock, "url": off.url,
            "valid": reason is None, "excluded_reason": reason, "suspect": suspect}


def _pick(o):
    return {"source": o.source, "offer_id": o.source_offer_id, "price_toman": _num(o.price_toman), "url": o.url}


def choose_variant(offers, priorities, settings, now, degraded, max_price=None):
    reasons = {id(o): invalid_reason(o, now, settings, degraded) for o in offers}
    valid = [o for o in offers if reasons[id(o)] is None]
    suspect_ids, warnings, needs_review = set(), [], False
    if len(valid) >= 3:
        med = median(o.price_toman for o in valid)
        r = max(settings.outlier_ratio, 1.0)
        for o in valid:
            if not (med / r <= o.price_toman <= med * r):
                suspect_ids.add(id(o))
        if suspect_ids:
            warnings.append(f"{len(suspect_ids)} قیمت پرت نسبت به میانه حذف شد")
    elif len(valid) == 2:
        lo, hi = sorted(o.price_toman for o in valid)
        if hi / lo > settings.outlier_ratio:
            suspect_ids = {id(o) for o in valid}
            needs_review = True
            warnings.append("اختلاف قیمت دو منبع غیرعادی است؛ نمی‌توان تشخیص داد کدام درست است (نیاز به بازبینی)")
    candidates = [o for o in valid if id(o) not in suspect_ids] or valid
    candidates.sort(key=lambda o: (o.price_toman, priorities.get(o.source, 100), o.source, o.source_offer_id))
    res = {"offers": [_offer_dict(o, reasons[id(o)], id(o) in suspect_ids) for o in offers],
           "winner": None, "runner_up": None, "savings": None, "why": "", "needs_review": needs_review,
           "warnings": warnings}
    if not candidates:
        res["why"] = "هیچ پیشنهاد معتبری وجود ندارد"
        return res, None
    win = candidates[0]
    res["winner"] = _pick(win)
    if max_price and win.price_toman > max_price:
        res["warnings"].append(f"قیمت برنده بالاتر از سقف تعیین‌شده ({max_price:,.0f}) است")
    run = next((o for o in candidates[1:] if o.source_offer_id != win.source_offer_id or o.source != win.source), None)
    if run:
        res["runner_up"] = _pick(run)
        amt = run.price_toman - win.price_toman
        pct = amt / run.price_toman * 100 if run.price_toman else 0
        res["savings"] = {"amount_toman": _num(amt), "percent": round(pct, 2)}
        if amt == 0:
            res["why"] = f"تساوی قیمت با {run.source}؛ منبع با اولویت بالاتر ({win.source}) انتخاب شد"
        else:
            res["why"] = f"ارزان‌ترین پیشنهاد معتبر؛ {amt:,.0f} تومان ({pct:.1f}٪) ارزان‌تر از {run.source}"
    else:
        res["why"] = "تنها پیشنهاد معتبر"
    return res, win


def build_product(watch, matched, priorities, settings, now, degraded):
    """matched: list[(offer, MatchResult)] for this watch item."""
    groups, ignored = {}, []
    for off, _ in matched:
        if watch.colors != ["any"] and off.color not in watch.colors:
            ignored.append({"source": off.source, "offer_id": off.source_offer_id, "reason": "رنگ درخواست‌نشده"})
            continue
        parts = variant_parts(off, watch)
        groups.setdefault(tuple(parts.items()), []).append(off)
    variants = []
    for key, offs in sorted(groups.items(), key=lambda kv: str(kv[0])):
        parts = dict(key)
        res, _ = choose_variant(offs, priorities, settings, now, degraded, watch.max_price)
        for attr, name, fixed in (("region", "ریجن", watch.region), ("condition", "وضعیت اکتیو", watch.condition)):
            known = sorted({getattr(o, attr) for o in offs if getattr(o, attr)})
            if len(known) > 1 and not fixed:
                res["warnings"].append(f"{name} پیشنهادها یکسان نیست ({', '.join(known)}) — در watchlist مشخصش کنید")
                res["needs_review"] = True
        res.update({"variant": variant_label(parts), "attributes": parts})
        variants.append(res)
    if not matched:
        status = "not_found"
    elif any(v["winner"] for v in variants):
        status = "found"
    else:
        status = "no_valid_price"
    return {"id": watch.id, "brand": watch.brand, "model": watch.model, "storage_gb": watch.storage_gb,
            "ram_gb": watch.ram_gb, "region": watch.region, "condition": watch.condition,
            "status": status, "variants": variants, "ignored_offers": ignored}


def scale_check(products, settings):
    """Detect a systematic ~10x (toman/rial) gap between two sources across shared variants."""
    per = {}   # (product, variant) -> {source: min valid price}
    for p in products:
        for v in p["variants"]:
            d = {}
            for o in v["offers"]:
                if o["valid"]:
                    d[o["source"]] = min(d.get(o["source"], o["price_toman"]), o["price_toman"])
            per[(p["id"], v["variant"])] = d
    warnings, bad_pairs = [], set()
    sources = sorted({s for d in per.values() for s in d})
    for a, b in combinations(sources, 2):
        ratios = [d[a] / d[b] for d in per.values() if a in d and b in d and d[b] > 0]
        if len(ratios) < settings.scale_check_min_pairs:
            continue
        m = median(ratios)
        if 8 <= m <= 12 or 1 / 12 <= m <= 1 / 8:
            bad_pairs.add((a, b))
            warnings.append(f"احتمال خطای واحد ریال/تومان بین «{a}» و «{b}» (نسبت میانه {m:.2f}). "
                            f"واحد currency_unit منبع‌ها را بررسی کنید.")
    if bad_pairs:
        for p in products:
            for v in p["variants"]:
                srcs = {o["source"] for o in v["offers"] if o["valid"]}
                if any(a in srcs and b in srcs for a, b in bad_pairs):
                    v["needs_review"] = True
                    v["warnings"].append("احتمال ناسازگاری واحد قیمت بین منابع؛ نیاز به بازبینی")
    return warnings
