"""V2 §7: per-vendor price tracking, drop/opportunity alerts, thresholds, dedup, persistence."""
import json
from pathlib import Path
import yaml
from conftest_helpers import make_project
from pricecompare import history, telegram
from pricecompare.runner import run

NOW = "2026-10-06T09:00:00+00:00"


def _proj(tmp_path, **settings):
    base = {"telegram_enabled": False, "price_alert_drop_pct": 1.0, "price_alert_market_beat_pct": 0.5}
    base.update(settings)
    return make_project(tmp_path, settings=base)


def _last_history(tmp_path):
    f = tmp_path / "history.jsonl"
    return json.loads(f.read_text(encoding="utf-8").splitlines()[-1])


def _bump_prev_price(tmp_path, key, source, factor):
    """Rewrite the LAST history line so `source`'s previous price = price*factor (a fake baseline)."""
    f = tmp_path / "history.jsonl"
    lines = f.read_text(encoding="utf-8").splitlines()
    rec = json.loads(lines[-1])
    rec["source_prices"][key][source]["price"] = int(rec["source_prices"][key][source]["price"] * factor)
    lines[-1] = json.dumps(rec, ensure_ascii=False)
    f.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _entry(changes, pid, variant, source):
    return next(c for c in changes if c["product_id"] == pid and c["variant"] == variant and c["source"] == source)


def test_first_run_registers_base_prices_without_alerts(tmp_path):
    cfg, base = _proj(tmp_path)
    res = run(cfg, base_dir=base)
    assert res.exit_code == 0
    ch = res.doc["price_changes"]
    assert ch and all(c["type"] == "base_registered" for c in ch)
    assert all(c.get("note") == "قیمت پایه در حال ثبت" for c in ch)
    assert res.doc["alerts"] == []
    rec = _last_history(tmp_path)
    assert rec["source_prices"]["iphone17-256|black"]["shop_a"]["price"] == 64_900_000
    assert (tmp_path / "alerts.jsonl").exists()


def test_vendor_drop_detected_with_amount_percent_and_timestamps(tmp_path):
    cfg, base = _proj(tmp_path)
    run(cfg, base_dir=base)
    _bump_prev_price(tmp_path, "iphone17-256|black", "shop_a", 1.10)   # pretend it was dearer
    res = run(cfg, base_dir=base)
    e = _entry(res.doc["price_changes"], "iphone17-256", "black", "shop_a")
    assert e["type"] == "vendor_drop" and e["alert"] is True
    assert e["prev_price"] == 71_390_000 and e["new_price"] == 64_900_000
    assert e["amount_toman"] == -6_490_000
    assert abs(e["percent"] - (64_900_000 - 71_390_000) / 71_390_000 * 100) < 0.01   # ((new-old)/old)*100
    assert e["prev_recorded_at"] and e["recorded_at"]
    assert e in res.doc["alerts"]
    # the alert is also persisted (append-only) with both timestamps
    rows = [json.loads(x) for x in (tmp_path / "alerts.jsonl").read_text(encoding="utf-8").splitlines()]
    assert any(r["type"] == "vendor_drop" and r["source"] == "shop_a" for r in rows)


def test_increase_is_detected_but_not_an_opportunity_alert(tmp_path):
    cfg, base = _proj(tmp_path)
    run(cfg, base_dir=base)
    _bump_prev_price(tmp_path, "iphone17-256|black", "shop_a", 0.9)    # pretend it was 10% cheaper
    res = run(cfg, base_dir=base)
    e = _entry(res.doc["price_changes"], "iphone17-256", "black", "shop_a")
    assert e["type"] == "vendor_increase" and e["alert"] is False
    assert abs(e["percent"] - (64_900_000 - 58_410_000) / 58_410_000 * 100) < 0.01


def test_change_below_threshold_is_recorded_but_not_alerted(tmp_path):
    cfg, base = _proj(tmp_path, price_alert_drop_pct=5.0)
    run(cfg, base_dir=base)
    _bump_prev_price(tmp_path, "iphone17-256|black", "shop_a", 1.02)   # ~2% drop < 5% threshold
    res = run(cfg, base_dir=base)
    e = _entry(res.doc["price_changes"], "iphone17-256", "black", "shop_a")
    assert e["type"] is None and e["alert"] is False                    # change still recorded
    assert abs(e["percent"] - (64_900_000 - 66_198_000) / 66_198_000 * 100) < 0.01
    assert not any(c["product_id"] == "iphone17-256" and c["alert"] for c in res.doc["alerts"])


def test_stale_baseline_is_never_used_for_percent(tmp_path):
    cfg, base = _proj(tmp_path, vendor_price_compare_max_hours=1)
    run(cfg, base_dir=base)
    rec = _last_history(tmp_path)
    rec["run_at"] = "2026-10-01T09:00:00+00:00"                          # 5 days old baseline
    f = tmp_path / "history.jsonl"
    lines = f.read_text(encoding="utf-8").splitlines()
    lines[-1] = json.dumps(rec, ensure_ascii=False)
    f.write_text("\n".join(lines) + "\n", encoding="utf-8")
    res = run(cfg, base_dir=base)
    e = _entry(res.doc["price_changes"], "iphone17-256", "black", "shop_a")
    assert e["type"] == "base_registered" and e["prev_price"] is None    # re-registered, no bogus %


def test_market_best_alert_when_undercutting_the_previous_floor(tmp_path):
    cfg, base = _proj(tmp_path)
    run(cfg, base_dir=base)
    # blue: shop_b is the strict lowest (64.1M vs 64.2M/64.5M). Lift the WHOLE previous floor by
    # 0.6% (below the 1% vendor threshold) so ONLY the market-floor move fires.
    for src in ("shop_a", "shop_b", "shop_c"):
        _bump_prev_price(tmp_path, "iphone17-256|blue", src, 1.006)
    res = run(cfg, base_dir=base)
    e = _entry(res.doc["price_changes"], "iphone17-256", "blue", "shop_b")
    assert e["type"] == "market_best" and e["alert"] is True
    assert e["new_price"] == 64_100_000 and e["prev_price"] == int(64_100_000 * 1.006)


def test_alert_dedup_same_price_not_resent_new_drop_alerts_again(tmp_path, monkeypatch):
    cfg, base = _proj(tmp_path, telegram_enabled=True, telegram_dry_run=False)
    calls = []

    def fake_send(tok, chat, text, limit=2800, dry_run=True, **kw):
        calls.append(list(text) if not isinstance(text, str) else [text])
        return [str(len(calls))]

    monkeypatch.setattr(telegram, "send", fake_send)
    import os
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "123:abc")
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "42")
    run(cfg, base_dir=base)
    n0 = len(calls)
    _bump_prev_price(tmp_path, "iphone17-256|black", "shop_a", 1.10)
    run(cfg, base_dir=base)                                              # drop -> alert message
    n1 = len(calls)
    assert n1 > n0
    alert_msgs = [m for batch in calls for m in batch if "📉" in m]
    assert alert_msgs and "کاهش 9٪" in alert_msgs[-1]
    run(cfg, base_dir=base)                                              # nothing changed -> no new alert
    assert len(calls) == n1
    state = json.loads((tmp_path / "tg_alert_state.json").read_text(encoding="utf-8"))
    assert any(v["type"] == "vendor_drop" for v in state.values())


def test_unsent_alerts_dedup_logic():
    alerts = [{"type": "vendor_drop", "product_id": "p", "variant": "black", "source": "s",
               "new_price": 90, "prev_price": 100, "percent": -10.0, "amount_toman": -10,
               "recorded_at": NOW, "prev_recorded_at": None, "alert": True}]
    state = {history.alert_key(alerts[0]): {"price": 90, "type": "vendor_drop"}}
    assert history.unsent_alerts(alerts, state) == []                    # same price -> silent
    alerts[0]["new_price"] = 85                                          # further drop -> alert again
    assert history.unsent_alerts(alerts, state) == alerts


def test_out_of_stock_price_never_becomes_a_baseline(tmp_path):
    cfg, base = _proj(tmp_path)
    run(cfg, base_dir=base)
    rec = _last_history(tmp_path)
    # shop_a's colourless Redmi offer is out of stock -> it must not be in the per-source history
    assert "redmi-note-14-256-8|بدون رنگ/مشخصه" not in rec["source_prices"]
