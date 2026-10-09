"""Discovery: compare EVERY phone found in the sources, not only the watchlist.

Offers that no explicit watchlist entry claimed are clustered into products with the same hard constraints as the
matcher (brand, model core, tier words, 4G/5G, storage, RAM, region, activation). Each cluster is then priced per colour.
"""
from __future__ import annotations
import re
from .matcher import AUTO, evaluate
from .models import WatchItem

DISPLAY = {"iphone": "iPhone", "galaxy": "Galaxy", "redmi": "Redmi", "poco": "POCO", "pixel": "Pixel", "nokia": "Nokia"}
TIER_ORDER = ["pro", "max", "plus", "ultra", "air", "fe", "mini", "lite", "se", "edge", "fold", "flip", "neo", "turbo", "prime", "gt"]


def _completeness(o) -> int:
    return sum(bool(x) for x in (o.storage_gb, o.ram_gb, o.region, o.condition, o.network))


def display_name(core, tiers, network) -> str:
    def tok(t):
        if t in DISPLAY:
            return DISPLAY[t]
        if t.isdigit() or re.fullmatch(r"\d+[a-z]+", t):
            return t                                            # 17, 17e
        return t.upper() if re.search(r"\d", t) else t.capitalize()
    tiers = sorted(tiers, key=lambda t: TIER_ORDER.index(t) if t in TIER_ORDER else 99)
    return " ".join([tok(t) for t in core] + [t.capitalize() for t in tiers] + ([network.upper()] if network else []))


def _slug(*parts) -> str:
    return re.sub(r"[^a-z0-9]+", "-", "-".join(str(p) for p in parts if p not in (None, "", [])).lower()).strip("-")


class _Cluster:
    def __init__(self, seed, attrs, watch):
        self.watch, self.attrs, self.members = watch, attrs, []
        self.regions, self.conds, self.networks, self.strong_ids = set(), set(), set(), set()

    def add(self, o):
        self.members.append(o)
        if o.region:
            self.regions.add(o.region)
        if o.condition:
            self.conds.add(o.condition)
        if o.network:
            self.networks.add(o.network)
        from .canonical import strong_identifier
        sid = strong_identifier(o)
        if sid:
            self.strong_ids.add(sid)


def _joins(o, cl, settings) -> bool:
    w = cl.watch
    from .canonical import strong_identifier
    sid = strong_identifier(o)
    # A valid cross-source EAN/GTIN is the strongest identity signal.
    if sid and sid in cl.strong_ids:
        return True
    if o.storage_gb != w.storage_gb:
        return False
    if o.brand != w.brand:
        return False
    if o.ram_gb is not None and w.ram_gb is not None and o.ram_gb != w.ram_gb:
        return False
    if (o.ram_gb is None) != (w.ram_gb is None) and o.brand != "apple":
        return False
    if o.region and cl.regions and o.region not in cl.regions:
        return False
    if o.condition and cl.conds and o.condition not in cl.conds:
        return False
    # Unlike an unknown value, two different known networks must never merge.
    if (o.network is None or o.network == "") and cl.networks:
        return False
    if o.network and cl.networks and o.network not in cl.networks:
        return False
    if o.network and not cl.networks and getattr(w, "network", ""):
        if o.network != w.network:
            return False
    return evaluate(o, w, cl.attrs, settings).status == AUTO


def discover(offers, ex, settings, cfg, reserved_ids=()):
    """Return (watch_items, watch_attrs_by_id, members_by_id). Unknown region/activation is a wildcard; two DIFFERENT
    known regions/activations never share a product."""
    from .canonical import strong_identifier
    usable = [o for o in offers if o.price_toman and ((o.brand and o.model_core) or strong_identifier(o))]
    if cfg.brands:
        usable = [o for o in usable if o.brand in cfg.brands]
    if cfg.exclude_regex:
        rx = re.compile(cfg.exclude_regex, re.I)
        usable = [o for o in usable if not rx.search(o.raw_title)]
    usable.sort(key=lambda o: (-_completeness(o), o.source, o.source_offer_id))
    clusters, taken = [], set(reserved_ids)
    for o in usable:
        cl = next((c for c in clusters if _joins(o, c, settings)), None)
        if cl is None:
            canonical = " ".join(list(o.model_core) + list(o.tiers) + ([o.network] if o.network else []))
            attrs = ex.parse(canonical)
            base = _slug(o.brand, canonical, o.storage_gb and f"{o.storage_gb}gb", o.ram_gb and f"ram{o.ram_gb}")
            wid, n = base, 2
            while wid in taken:
                wid, n = f"{base}-{n}", n + 1
            taken.add(wid)
            w = WatchItem(id=wid, brand=o.brand, model=canonical, storage_gb=o.storage_gb, ram_gb=o.ram_gb, colors=["any"])
            w.network = o.network
            cl = _Cluster(o, attrs, w)
            clusters.append(cl)
        cl.add(o)
    items, attrs_by_id, members = [], {}, {}
    for cl in clusters:
        w = cl.watch
        w.region = next(iter(cl.regions)) if len(cl.regions) == 1 else None
        w.condition = next(iter(cl.conds)) if len(cl.conds) == 1 else None
        attrs_by_id[w.id], members[w.id] = cl.attrs, cl.members
        w.model = display_name(cl.attrs.core, cl.attrs.tiers, cl.attrs.network)     # pretty name AFTER identity is fixed
        items.append(w)
    return items, attrs_by_id, members
