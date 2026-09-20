"""Hard constraints first, fuzzy similarity last (and never alone)."""
from __future__ import annotations
from dataclasses import dataclass, field
from difflib import SequenceMatcher
from .models import Offer, WatchItem

AUTO, REVIEW, NO_MATCH = "AUTO_MATCH", "REVIEW", "NO_MATCH"


@dataclass
class MatchResult:
    status: str
    score: float
    watch_id: str
    reasons: list = field(default_factory=list)


def _ratio(a: list, b: list) -> float:
    return round(100 * SequenceMatcher(None, " ".join(sorted(a)), " ".join(sorted(b))).ratio(), 2)


def _has_digit(t: str) -> bool:
    return any(c.isdigit() for c in t)


def evaluate(offer: Offer, watch: WatchItem, watch_attrs, settings) -> MatchResult:
    """watch_attrs = Extractor.parse(watch.model) (core/tiers/network of the watch model)."""
    w = watch.id
    if watch.barcodes and str(offer.extra.get("barcode", "")) in watch.barcodes and offer.extra.get("barcode"):
        return MatchResult(AUTO, 100.0, w, ["barcode match"])
    reasons, review = [], []

    if offer.brand and watch.brand and offer.brand != watch.brand:
        return MatchResult(NO_MATCH, 0.0, w, [f"brand differs ({offer.brand} != {watch.brand})"])
    if not offer.brand:
        review.append("brand unknown")

    if sorted(offer.tiers) != sorted(watch_attrs.tiers):
        return MatchResult(NO_MATCH, 0.0, w,
                           [f"model tier differs (offer={offer.tiers or '-'} watch={watch_attrs.tiers or '-'})"])

    if watch.storage_gb:
        if offer.storage_gb is None:
            review.append("storage missing in offer")
        elif offer.storage_gb != watch.storage_gb:
            return MatchResult(NO_MATCH, 0.0, w, [f"storage differs ({offer.storage_gb}GB != {watch.storage_gb}GB)"])
    if watch.ram_gb and offer.ram_gb is not None and offer.ram_gb != watch.ram_gb:
        return MatchResult(NO_MATCH, 0.0, w, [f"RAM differs ({offer.ram_gb}GB != {watch.ram_gb}GB)"])
    if watch.region:
        if offer.region and offer.region != watch.region:
            return MatchResult(NO_MATCH, 0.0, w, [f"region differs ({offer.region} != {watch.region})"])
        if not offer.region:
            review.append("region missing in offer")
    if watch.condition in ("active", "nonactive"):
        if offer.condition and offer.condition != watch.condition:
            return MatchResult(NO_MATCH, 0.0, w, [f"activation differs ({offer.condition} != {watch.condition})"])
        if not offer.condition:
            review.append("activation status missing in offer")
    if watch_attrs.network and offer.network and watch_attrs.network != offer.network:
        return MatchResult(NO_MATCH, 0.0, w, [f"network differs ({offer.network} != {watch_attrs.network})"])

    oc, wc = list(offer.model_core), list(watch_attrs.core)
    if not oc or not wc:
        return MatchResult(NO_MATCH, 0.0, w, ["empty model identity"])
    if set(oc) == set(wc):
        score = 100.0
    else:
        if {t for t in oc if _has_digit(t)} != {t for t in wc if _has_digit(t)}:
            return MatchResult(NO_MATCH, 0.0, w, [f"model number differs ({' '.join(oc)} vs {' '.join(wc)})"])
        score = _ratio(oc, wc)
        if score < settings.match_review_threshold:
            return MatchResult(NO_MATCH, score, w, [f"model name too different (score {score})"])
        if score < settings.match_auto_threshold:
            review.append(f"model name similarity {score} below auto threshold")
    if review:
        return MatchResult(REVIEW, score, w, review)
    return MatchResult(AUTO, score, w, ["all hard constraints passed"] + reasons)


def assign(offers, watchlist, watch_attrs_by_id, settings, overrides):
    """Return (matched: {watch_id: [(offer, MatchResult)]}, report: list[dict], review_queue: list[dict])."""
    force_match = {(o["source"], str(o["source_offer_id"])): o["watch_id"] for o in overrides["force_match"]}
    force_split = {(o["source"], str(o["source_offer_id"])) for o in overrides["force_split"]}
    matched = {w.id: [] for w in watchlist}
    report, review_queue = [], []
    for off in offers:
        k = (off.source, off.source_offer_id)
        if k in force_split:
            report.append(_row(off, None, "FORCED_SPLIT", 0, ["overrides.yaml force_split"]))
            continue
        if k in force_match and force_match[k] in matched:
            r = MatchResult(AUTO, 100.0, force_match[k], ["overrides.yaml force_match"])
            matched[r.watch_id].append((off, r))
            report.append(_row(off, r.watch_id, AUTO, 100.0, r.reasons))
            continue
        results = sorted((evaluate(off, w, watch_attrs_by_id[w.id], settings) for w in watchlist),
                         key=lambda r: (-{AUTO: 2, REVIEW: 1, NO_MATCH: 0}[r.status], -r.score))
        if not results:                                   # empty explicit watchlist (discovery-only mode)
            report.append(_row(off, None, NO_MATCH, 0, ["no explicit watchlist entry"]))
            continue
        best = results[0]
        if best.status == AUTO and len(results) > 1 and results[1].status == AUTO and results[1].score == best.score:
            best = MatchResult(REVIEW, best.score, best.watch_id,
                               [f"ambiguous: also matches {results[1].watch_id}"])
        if best.status == NO_MATCH:
            def closeness(r):
                wc = set(watch_attrs_by_id[r.watch_id].core)
                return (not r.reasons[0].startswith("brand differs"), len(wc & set(off.model_core)), r.score)
            nearest = max(results, key=closeness)
            report.append(_row(off, None, NO_MATCH, nearest.score,
                               [f"nearest={nearest.watch_id}: " + "; ".join(nearest.reasons)]))
            continue
        report.append(_row(off, best.watch_id, best.status, best.score, best.reasons))
        if best.status == REVIEW:
            review_queue.append(_row(off, best.watch_id, REVIEW, best.score, best.reasons))
            if not settings.review_as_match:
                continue
        matched[best.watch_id].append((off, best))
    return matched, report, review_queue


def _row(off, watch_id, status, score, reasons):
    return {"source": off.source, "offer_id": off.source_offer_id, "title": off.raw_title,
            "watch_id": watch_id, "status": status, "score": score, "reasons": reasons}


def best_result(off, watchlist, watch_attrs_by_id, settings):
    """Most relevant watch item for an offer (used by diagnostics): AUTO/REVIEW first, else the closest miss."""
    results = [evaluate(off, w, watch_attrs_by_id[w.id], settings) for w in watchlist]

    def key(r):
        wc = set(watch_attrs_by_id[r.watch_id].core)
        return ({AUTO: 2, REVIEW: 1, NO_MATCH: 0}[r.status], not r.reasons[0].startswith("brand differs"),
                len(wc & set(off.model_core)), r.score)
    return max(results, key=key)
