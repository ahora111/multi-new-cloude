import json
from conftest_helpers import make_project
from pricecompare import telegram
from pricecompare.report import build_telegram
from pricecompare.runner import run

TOKEN = "123456:SECRET-TOKEN"


def _proj(tmp_path, **settings):
    base = {"telegram_enabled": True, "telegram_dry_run": False}
    base.update(settings)
    return make_project(tmp_path, settings=base)


def _spy(monkeypatch, fail=None):
    calls = []

    def fake(token, chat, text, limit=2800, dry_run=True, **kw):
        if fail:
            raise fail
        calls.append({"token": token, "chat": chat, "text": text, "dry_run": dry_run})
        return telegram.split_message(text, limit)
    monkeypatch.setattr(telegram, "send", fake)
    return calls


def _env(monkeypatch, on=True):
    if on:
        monkeypatch.setenv("TELEGRAM_BOT_TOKEN", TOKEN)
        monkeypatch.setenv("TELEGRAM_CHAT_ID", "42")
    else:
        monkeypatch.delenv("TELEGRAM_BOT_TOKEN", raising=False)
        monkeypatch.delenv("TELEGRAM_CHAT_ID", raising=False)


def test_message_is_plain_text_and_useful(tmp_path, monkeypatch):
    cfg, base = _proj(tmp_path); calls = _spy(monkeypatch); _env(monkeypatch)
    res = run(cfg, base_dir=base)
    assert res.exit_code == 0 and res.summary["telegram"].startswith("sent")
    text = calls[0]["text"]
    assert "🏆 shop_b 64,100,000" in text and "❌ پیدا نشد: pixel-10-pro-256" in text
    assert "##" not in text and "**" not in text                      # no Markdown noise in Telegram
    assert calls[0]["chat"] == "42" and calls[0]["dry_run"] is False


def test_missing_secrets_is_a_loud_failure_not_silence(tmp_path, monkeypatch):
    cfg, base = _proj(tmp_path); calls = _spy(monkeypatch); _env(monkeypatch, on=False)
    res = run(cfg, base_dir=base)
    assert res.exit_code == 6 and "TELEGRAM_BOT_TOKEN" in res.summary["telegram"] and not calls
    assert (tmp_path / "out" / "output.json").exists()                # data is still saved


def test_only_sent_when_something_changed(tmp_path, monkeypatch):
    cfg, base = _proj(tmp_path); calls = _spy(monkeypatch); _env(monkeypatch)
    run(cfg, base_dir=base)
    r2 = run(cfg, base_dir=base)
    assert len(calls) == 1 and "unchanged" in r2.summary["telegram"]
    hist = tmp_path / "history.jsonl"
    rec = json.loads(hist.read_text(encoding="utf-8").splitlines()[-1])
    k = next(iter(rec["prices"])); rec["prices"][k]["price"] += 1000   # pretend last time the price differed
    hist.write_text(json.dumps(rec) + "\n", encoding="utf-8")
    run(cfg, base_dir=base)
    assert len(calls) == 2


def test_only_on_change_setting_is_used(tmp_path, monkeypatch):
    cfg, base = _proj(tmp_path, telegram_only_on_change=False); calls = _spy(monkeypatch); _env(monkeypatch)
    run(cfg, base_dir=base); run(cfg, base_dir=base)
    assert len(calls) == 2


def test_dry_run_flags_and_no_telegram_switch(tmp_path, monkeypatch):
    cfg, base = _proj(tmp_path / "a", telegram_dry_run=True); calls = _spy(monkeypatch); _env(monkeypatch)
    assert "NOT sent" in run(cfg, base_dir=base).summary["telegram"]     # settings dry-run: build only
    cfg2, base2 = _proj(tmp_path / "b")
    assert "--no-telegram" in run(cfg2, base_dir=base2, send_telegram=False).summary["telegram"]
    cfg3, base3 = _proj(tmp_path / "c", telegram_enabled=False)
    assert "disabled" in run(cfg3, base_dir=base3).summary["telegram"]
    assert "nothing written" in run(cfg2, base_dir=base2, dry_run=True).summary["telegram"]


def test_send_error_never_leaks_the_bot_token(tmp_path, monkeypatch):
    cfg, base = _proj(tmp_path); _env(monkeypatch)
    _spy(monkeypatch, fail=RuntimeError(f"400 Client Error for url: https://api.telegram.org/bot{TOKEN}/sendMessage"))
    res = run(cfg, base_dir=base)
    assert res.exit_code == 6 and "FAILED" in res.summary["telegram"] and TOKEN not in res.summary["telegram"]
    assert TOKEN not in json.dumps(res.doc, ensure_ascii=False)


def test_health_check_uses_catalog_size_not_watchlist_subset(tmp_path):
    """Regression: Eways returned 7 relevant offers out of a large catalog and was wrongly marked degraded."""
    from pricecompare.sources.base import Source
    import pricecompare.sources as srcs

    class Big(Source):
        def records(self, watchlist):
            self.raw_count = 500                     # whole catalog
            return [{"id": "1", "title": "iPhone 17 256GB Blue", "price": 64_000_000, "stock": "1"}]
    srcs.REGISTRY["big_test"] = Big
    try:
        for need, expect in ((100, "ok"), (1000, "degraded")):
            cfg, base = make_project(tmp_path / str(need), sources=[{"name": "big", "type": "big_test", "currency_unit": "toman",
                                                                      "min_expected_products": need}])
            res = run(cfg, base_dir=base)
            st = res.doc["sources"][0]
            assert st["status"] == expect and st["catalog_count"] == 500 and st["count"] == 1
    finally:
        del srcs.REGISTRY["big_test"]
