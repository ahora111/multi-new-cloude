"""V2 §3: shared update cycle — parallel fetching, failure isolation, source statuses, snapshots."""
import json
from datetime import datetime, timedelta, timezone
import pytest
import yaml
from conftest_helpers import make_project, load_sources_yaml
from pricecompare import sources as srcs
from pricecompare.models import Offer
from pricecompare.runner import run, _offers_all_older_than
from pricecompare.sources.base import Source

NOW = datetime.now(timezone.utc)


class OldSource(Source):
    """A source whose whole catalog was fetched long ago (its own clock/cache is stale)."""
    type_name = "old_test"

    def records(self, watchlist):
        return [{"id": "1", "title": "iPhone 17 256GB Black", "price": 60_000_000}]

    def fetch(self, watchlist):
        stamp = (NOW - timedelta(hours=12)).isoformat()
        return [Offer(self.name, "1", "iPhone 17 256GB Black", 600_000_000, "rial",
                      stock="IN_STOCK", fetched_at=stamp)]


class DelayedSource(Source):
    type_name = "delayed_test"

    def records(self, watchlist):
        import time
        time.sleep(0.8)                       # long enough to prove the other source didn't wait
        return [{"id": "1", "title": "iPhone 17 256GB Black", "price": 61_000_000}]


@pytest.fixture
def register():
    def _reg(cls):
        srcs.REGISTRY[cls.type_name] = cls
        return cls
    yield _reg
    for c in (OldSource, DelayedSource):
        srcs.REGISTRY.pop(c.type_name, None)


def test_cycle_metadata_and_source_status_fields(tmp_path):
    cfg, base = make_project(tmp_path)
    res = run(cfg, base_dir=base)
    assert res.exit_code == 0
    cyc = res.doc["cycle"]
    assert cyc["interval_minutes"] == 60 and cyc["timezone"] == "Asia/Tehran"
    assert cyc["started_at"] and cyc["finished_at"] and cyc["started_at"] < cyc["finished_at"]
    st = {s["name"]: s for s in res.doc["sources"]}
    for s in st.values():
        assert s["status_fa"] == {"ok": "موفق", "degraded": "ناقص", "failed": "ناموفق",
                                  "stale": "داده قدیمی", "cached": "از کش"}[s["status"]]
        assert s["fetch_started_at"] and s["fetched_at"] and s["seconds"] >= 0


def test_sources_run_in_parallel(tmp_path, register):
    register(DelayedSource)
    src_rows = [{"name": "slow", "type": "delayed_test", "currency_unit": "toman"},
                {"name": "fast_a", "type": "json", "currency_unit": "toman", "path": "fixtures/shop_a.json",
                 "items_path": "data.products", "base_url": "https://x", "min_expected_products": 1,
                 "fields": {"id": "id", "title": "name", "price": "price", "stock": "available",
                            "url": "link", "color": "color"}}]
    cfg, base = make_project(tmp_path / "p", sources=src_rows, settings={"cycle_max_workers": 2})
    import time
    t0 = time.monotonic()
    res = run(cfg, base_dir=base)
    took = time.monotonic() - t0
    assert res.exit_code == 0 and res.summary["sources_ok"] == 2
    assert took < 1.6, f"sources ran sequentially ({took:.2f}s), parallelism is broken"


def test_one_broken_source_does_not_stop_the_cycle(tmp_path):
    cfg, base = make_project(tmp_path)
    srcs_rows = load_sources_yaml(tmp_path)
    srcs_rows[0]["path"] = "fixtures/does_not_exist.json"        # shop_a fails
    cfg, base = make_project(tmp_path / "q", sources=srcs_rows)
    res = run(cfg, base_dir=base)
    assert res.exit_code == 0
    st = {s["name"]: s for s in res.doc["sources"]}
    assert st["shop_a"]["status"] == "failed" and st["shop_b"]["status"] == "ok"
    assert res.summary["sources_failed"] == 1 and res.summary["sources_ok"] >= 2
    assert any("shop_a" in w for w in res.doc["warnings"])


def test_degraded_partial_and_failed_are_distinguished(tmp_path):
    srcs_rows = load_sources_yaml(tmp_path) if False else yaml.safe_load(
        open(__import__("pathlib").Path(__file__).parent.parent / "config" / "sources.yaml", encoding="utf-8"))["sources"]
    srcs_rows[0]["min_expected_products"] = 500                  # shop_a -> degraded (partial data)
    srcs_rows[1]["path"] = "fixtures/none.html"                  # shop_b -> failed
    cfg, base = make_project(tmp_path / "d", sources=srcs_rows)
    res = run(cfg, base_dir=base)
    st = {s["name"]: s for s in res.doc["sources"]}
    assert st["shop_a"]["status"] == "degraded" and st["shop_a"]["status_fa"] == "ناقص"
    assert st["shop_b"]["status"] == "failed" and st["shop_b"]["status_fa"] == "ناموفق"


def test_stale_source_status_and_old_price_never_wins(tmp_path, register):
    register(OldSource)
    cfg, base = make_project(tmp_path / "s", sources=[
        {"name": "old_src", "type": "old_test", "currency_unit": "rial", "priority": 1},
        {"name": "fresh", "type": "json", "currency_unit": "toman", "path": "fixtures/shop_a.json",
         "items_path": "data.products", "base_url": "https://x", "fields":
             {"id": "id", "title": "name", "price": "price", "stock": "available", "url": "link", "color": "color"}}],
        watchlist=[{"id": "ip17", "brand": "apple", "model": "iPhone 17", "storage": 256}])
    res = run(cfg, base_dir=base)
    st = {s["name"]: s for s in res.doc["sources"]}
    assert st["old_src"]["status"] == "stale" and st["old_src"]["status_fa"] == "داده قدیمی"
    # the stale offer is the CHEAPEST (60M) but must never win over the fresh 64.9M
    p = next(p for p in res.doc["products"] if p["id"] == "ip17")
    black = next(v for v in p["variants"] if v["variant"] == "black")
    assert black["winner"]["source"] == "fresh"
    old_offer = next(o for o in black["offers"] if o["source"] == "old_src")
    assert not old_offer["valid"] and "قدیمی" in old_offer["excluded_reason"]


def test_min_fetch_interval_reuses_snapshot_and_preserves_fetched_at(tmp_path):
    fixture = tmp_path / "shop.json"
    fixture.write_text(json.dumps({"data": {"products": [
        {"id": "d1", "name": "iPhone 17 256GB Black", "price": 60_000_000, "available": 1, "link": "x"}]}}),
        encoding="utf-8")
    rows = [{"name": "snap", "type": "json", "currency_unit": "toman", "path": str(fixture),
             "items_path": "data.products", "base_url": "https://x", "min_fetch_interval_minutes": 120,
             "fields": {"id": "id", "title": "name", "price": "price", "stock": "available", "url": "link"}}]
    cfg, base = make_project(tmp_path / "a", sources=rows,
                             settings={"source_state_file": str(tmp_path / "a" / "state.json"),
                                       "source_snapshots_dir": str(tmp_path / "a" / "snaps")})
    r1 = run(cfg, base_dir=base)
    assert {s["name"]: s["status"] for s in r1.doc["sources"]}["snap"] == "ok"
    # the underlying data CHANGES between the two cycles (same matchable title, new price)…
    fixture.write_text(json.dumps({"data": {"products": [
        {"id": "d1", "name": "iPhone 17 256GB Black", "price": 55_000_000, "available": 1, "link": "x"}]}}),
        encoding="utf-8")
    r2 = run(cfg, base_dir=base)
    st = {s["name"]: s for s in r2.doc["sources"]}["snap"]
    assert st["status"] == "cached" and st["status_fa"] == "از کش"
    # …but the SNAPSHOT price (60M) was used, not the new 55M one
    p2 = next(p for p in r2.doc["products"] if p["id"] == "iphone17-256")
    black2 = next(v for v in p2["variants"] if v["variant"] == "black")
    assert black2["winner"]["price_toman"] == 60_000_000
    snap_offers = [o["fetched_at"] for p in r2.doc["products"] for v in p["variants"]
                   for o in v["offers"] if o["source"] == "snap"]
    assert st["fetched_at"] == snap_offers[0]                    # REAL original extraction time kept
    # after the interval expires the source is really fetched again
    state = json.loads((tmp_path / "a" / "state.json").read_text(encoding="utf-8"))
    state["snap"]["last_ok_fetch_at"] = (datetime.now(timezone.utc) - timedelta(hours=3)).isoformat()
    (tmp_path / "a" / "state.json").write_text(json.dumps(state), encoding="utf-8")
    r3 = run(cfg, base_dir=base)
    assert {s["name"]: s["status"] for s in r3.doc["sources"]}["snap"] == "ok"
    p3 = next(p for p in r3.doc["products"] if p["id"] == "iphone17-256")
    black3 = next(v for v in p3["variants"] if v["variant"] == "black")
    assert black3["winner"]["price_toman"] == 55_000_000         # fresh data this time


def test_overlapping_cycles_cannot_duplicate_history(tmp_path):
    cfg, base = make_project(tmp_path)
    assert run(cfg, base_dir=base).exit_code == 0
    hist = tmp_path / "history.jsonl"
    n = len(hist.read_text(encoding="utf-8").splitlines())
    (tmp_path / "run.lock").write_text(str(__import__("os").getpid()), encoding="utf-8")
    res = run(cfg, base_dir=base)                                # a second cycle while one "runs"
    assert res.exit_code == 5                                    # blocked by the lock: no duplicate rows
    assert len(hist.read_text(encoding="utf-8").splitlines()) == n


def test_source_state_file_survives_and_accumulates(tmp_path):
    cfg, base = make_project(tmp_path, settings={"source_state_file": str(tmp_path / "st.json")})
    run(cfg, base_dir=base)
    run(cfg, base_dir=base)
    state = json.loads((tmp_path / "st.json").read_text(encoding="utf-8"))
    assert "shop_a" in state and state["shop_a"]["last_status"] == "ok"
    assert state["shop_a"]["consecutive_failures"] == 0 and state["shop_a"]["last_ok_fetch_at"]


def test_offers_all_older_than_helper():
    old = [(NOW - timedelta(hours=5)).isoformat()]
    offers = [Offer("s", "1", "t", 1, "toman", fetched_at=old[0])]
    assert _offers_all_older_than(offers, 180, NOW)
    fresh = [Offer("s", "2", "t", 1, "toman", fetched_at=NOW.isoformat())]
    assert not _offers_all_older_than(fresh, 180, NOW)
    assert not _offers_all_older_than([], 180, NOW)
