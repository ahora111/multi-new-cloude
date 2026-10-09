"""LIVE smoke test: real internet + your real credentials. Deselected by default (see pytest.ini).

Run on your machine:   PRICECOMPARE_LIVE_CONFIG=config pytest -m live -s
It fetches every enabled source, then asserts basic sanity (non-empty, prices in a plausible range, no unit mix-up).
"""
import os
import pytest
from pricecompare.runner import run


@pytest.mark.live
def test_live_sources_return_sane_data():
    cfg = os.environ.get("PRICECOMPARE_LIVE_CONFIG")
    if not cfg:
        return                                    # not configured -> nothing to check
    res = run(cfg, dry_run=True)
    assert res.exit_code == 0, res.message
    assert all(s["status"] == "ok" for s in res.summary["sources"]), res.summary["sources"]
    assert not any("ریال/تومان" in w for w in res.doc["warnings"]), res.doc["warnings"]
