from pricecompare.telegram import split_message, utf16_len, send


def test_split_respects_utf16_limit_with_persian_and_emoji():
    text = "\n".join(f"🔹 خط شماره {i} — قیمت ۶۴٬۵۰۰٬۰۰۰ تومان ✅" for i in range(200))
    parts = split_message(text, 500)
    assert len(parts) > 1 and all(utf16_len(p) <= 500 for p in parts)
    assert "\n".join(parts).replace("\n", "") == text.replace("\n", "")


def test_overlong_single_line_is_hard_split():
    parts = split_message("الف" * 1000, 100)
    assert all(utf16_len(p) <= 100 for p in parts) and "".join(parts) == "الف" * 1000


class _R:
    def __init__(self, code, body=None):
        self.status_code, self._b = code, body or {}
    def json(self): return self._b
    def raise_for_status(self):
        if self.status_code >= 400: raise RuntimeError(self.status_code)


class _S:
    def __init__(self): self.calls = []
    def post(self, url, json=None, timeout=None):
        self.calls.append(json)
        return _R(429, {"parameters": {"retry_after": 3}}) if len(self.calls) == 1 else _R(200)


def test_telegram_honours_429_retry_after_and_dry_run_sends_nothing():
    s, waits = _S(), []
    send("t", "c", "سلام", dry_run=False, session=s, sleep=waits.append)
    assert len(s.calls) == 2 and 3 in waits
    s2 = _S()
    assert send("t", "c", "سلام", dry_run=True, session=s2) == ["سلام"] and not s2.calls


def test_dotenv_loader_does_not_override_existing_env(tmp_path, monkeypatch):
    import os
    from pricecompare.cli import load_dotenv
    f = tmp_path / ".env"
    f.write_text('# c\nA_NEW=1\nA_KEEP="from-file"\nEMPTY=\nbad line\n', encoding="utf-8")
    monkeypatch.setenv("A_KEEP", "from-env")
    monkeypatch.delenv("A_NEW", raising=False) if hasattr(monkeypatch, "delenv") else None
    try:
        assert load_dotenv(str(f)) == 1
        assert os.environ["A_NEW"] == "1" and os.environ["A_KEEP"] == "from-env" and "EMPTY" not in os.environ
    finally:
        os.environ.pop("A_NEW", None)
