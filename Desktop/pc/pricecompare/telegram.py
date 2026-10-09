"""Optional Telegram delivery: split by UTF-16 length, honour 429 retry_after."""
import time
import requests


def utf16_len(s: str) -> int:
    return len(s.encode("utf-16-le")) // 2


def split_message(text: str, limit: int) -> list:
    chunks, cur = [], ""
    for line in text.splitlines(True):
        while utf16_len(line) > limit:                       # hard-split an over-long line
            head = line
            while utf16_len(head) > limit:
                head = head[:-1]
            if cur:
                chunks.append(cur.rstrip("\n")); cur = ""
            chunks.append(head)
            line = line[len(head):]
        if cur and utf16_len(cur + line) > limit:
            chunks.append(cur.rstrip("\n")); cur = line
        else:
            cur += line
    if cur.strip():
        chunks.append(cur.rstrip("\n"))
    return chunks


def send(token, chat_id, text, limit=2800, dry_run=True, session=None, sleep=time.sleep, max_messages=None):
    """`text` may be one string (split by size, numbered) or a list of messages (each becomes >= 1 separate post)."""
    numbered = isinstance(text, str)
    parts = []
    for t in ([text] if numbered else list(text)):
        parts += split_message(t, limit)
    if max_messages and len(parts) > max_messages:
        dropped = len(parts) - max_messages + 1
        parts = parts[:max_messages - 1] + [f"… {dropped} پیام دیگر به‌خاطر سقف telegram_max_messages ارسال نشد (گزارش کامل در فایل‌های خروجی)."]
    if dry_run:
        return parts
    s = session or requests.Session()
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    for i, part in enumerate(parts, 1):
        body = f"({i}/{len(parts)})\n{part}" if numbered and len(parts) > 1 else part
        for attempt in range(4):
            r = s.post(url, json={"chat_id": chat_id, "text": body}, timeout=20)
            if r.status_code == 429:
                try:
                    wait = int(r.json().get("parameters", {}).get("retry_after", 2))
                except (ValueError, TypeError):
                    wait = 2
                sleep(max(wait, 1)); continue
            r.raise_for_status()
            break
        else:
            raise RuntimeError("Telegram rate limit persisted")
        sleep(1.1)
    return parts
