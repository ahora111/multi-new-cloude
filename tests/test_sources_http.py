import http.server
import json
import threading
from conftest_helpers import ROOT
from pricecompare.config import SourceConfig
from pricecompare.httpclient import HttpClient, HttpError
from pricecompare.sources import build_source
from pricecompare.sources.base import Source


def cfg(**kw):
    opts = kw.pop("options", {})
    return SourceConfig(name=kw.pop("name", "s"), type=kw.pop("type", "json"), currency_unit=kw.pop("currency_unit", "toman"), options=opts, **kw)


def _fixture_cfg(kind):
    import yaml
    for s in yaml.safe_load((ROOT / "config" / "sources.yaml").read_text(encoding="utf-8"))["sources"]:
        if s["type"] == kind:
            core = {"name", "type", "currency_unit", "priority", "min_expected_products"}
            return SourceConfig(s["name"], s["type"], s["currency_unit"], options={k: v for k, v in s.items() if k not in core})


def test_json_html_csv_fixtures_parse():
    for kind, n in (("json", 10), ("html", 7), ("csv", 6)):
        offers = build_source(_fixture_cfg(kind), base_dir=str(ROOT)).fetch([])
        assert len(offers) == n and all(o.price_raw and o.currency_unit_raw for o in offers), kind


def test_stock_and_url_and_persian_digits_are_parsed():
    a = {o.source_offer_id: o for o in build_source(_fixture_cfg("json"), base_dir=str(ROOT)).fetch([])}
    assert a["a8"].stock == "OUT_OF_STOCK" and a["a1"].url == "https://shop-a.example/product/a1"
    b = {o.source_offer_id: o for o in build_source(_fixture_cfg("html"), base_dir=str(ROOT)).fetch([])}
    assert b["b1"].price_raw == 641_000_000 and b["b1"].currency_unit_raw == "rial"
    c = {o.source_offer_id: o for o in build_source(_fixture_cfg("csv"), base_dir=str(ROOT)).fetch([])}
    assert c["c1"].price_raw == 64_200_000


def test_unknown_type_and_missing_config_give_clear_errors():
    for c, text in ((cfg(type="nope"), "unknown type"), (cfg(options={"fields": {"title": "a"}}), None)):
        try:
            build_source(c).fetch([])
        except ValueError as exc:
            if text:
                assert text in str(exc)
        else:
            raise AssertionError("expected ValueError")


class _Custom(Source):
    def records(self, watchlist):
        return [{"id": "1", "title": "iPhone 17 256GB", "price": "10", "stock": "1"}]


def test_custom_source_class_plugs_in_without_touching_core():
    s = build_source(cfg(type="custom", options={"class": "test_sources_http:_Custom"}))
    assert s.fetch([])[0].raw_title == "iPhone 17 256GB"


# ---------- real HTTP against a local server ----------
class _H(http.server.BaseHTTPRequestHandler):
    hits = {}

    def log_message(self, *a):
        pass

    def do_GET(self):
        n = _H.hits[self.path] = _H.hits.get(self.path, 0) + 1
        if self.path == "/flaky" and n < 3:
            self.send_response(503); self.end_headers(); return
        if self.path == "/missing":
            self.send_response(404); self.end_headers(); return
        if self.path == "/auth" and self.headers.get("X-Token") != "s3cret":
            self.send_response(401); self.end_headers(); return
        body = json.dumps({"ok": True}).encode()
        self.send_response(200); self.send_header("Content-Type", "application/json; charset=utf-8"); self.end_headers()
        self.wfile.write(body)


def _server():
    srv = http.server.HTTPServer(("127.0.0.1", 0), _H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv, f"http://127.0.0.1:{srv.server_address[1]}"


def test_http_retries_5xx_with_backoff_then_succeeds():
    srv, base = _server(); slept = []
    try:
        c = HttpClient(rate_limit_per_sec=0, retries=3, backoff=1, sleep=slept.append)
        assert json.loads(c.get(base + "/flaky")) == {"ok": True}
        assert _H.hits["/flaky"] == 3 and slept[:2] == [1, 2]      # exponential backoff
    finally:
        srv.shutdown()


def test_http_404_is_not_retried_and_cache_avoids_second_request(tmp_path):
    srv, base = _server()
    try:
        c = HttpClient(rate_limit_per_sec=0, retries=3, sleep=lambda s: None, cache_dir=str(tmp_path), cache_ttl=60)
        try:
            c.get(base + "/missing")
        except HttpError as exc:
            assert "404" in str(exc)
        assert _H.hits["/missing"] == 1
        c.get(base + "/ok"); c.get(base + "/ok")
        assert _H.hits["/ok"] == 1
    finally:
        srv.shutdown()


def test_http_auth_from_env_and_missing_secret_error(monkeypatch):
    srv, base = _server()
    try:
        auth = {"type": "header", "name": "X-Token", "env": "SHOP_TOKEN"}
        try:
            HttpClient(auth=auth)
        except HttpError as exc:
            assert "SHOP_TOKEN" in str(exc)
        else:
            raise AssertionError("missing env not detected")
        monkeypatch.setenv("SHOP_TOKEN", "s3cret")
        assert HttpClient(rate_limit_per_sec=0, auth=auth).get(base + "/auth")
    finally:
        srv.shutdown()


def test_network_failure_becomes_http_error():
    c = HttpClient(rate_limit_per_sec=0, retries=1, timeout=1, sleep=lambda s: None)
    try:
        c.get("http://127.0.0.1:1/x")
    except HttpError as exc:
        assert "network error" in str(exc)
    else:
        raise AssertionError("expected HttpError")
