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


def send(token, chat_id, text, limit=2800, dry_run=True, session=None, sleep=time.sleep):
    parts = split_message(text, limit)
    if dry_run:
        return parts
    s = session or requests.Session()
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    for i, part in enumerate(parts, 1):
        for attempt in range(4):
            r = s.post(url, json={"chat_id": chat_id, "text": f"({i}/{len(parts)})\n{part}"}, timeout=20)
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
