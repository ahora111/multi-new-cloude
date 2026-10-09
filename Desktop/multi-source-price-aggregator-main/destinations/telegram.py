import time

import requests
from .base import Destination


class TelegramDestination(Destination):
    name = "telegram"

    # Telegram can return 429 for chat-level rate limits even when the bot
    # itself is healthy. Keep requests sparse and honor retry_after exactly.
    MIN_REQUEST_INTERVAL = 1.1
    # Telegram limits text messages to 4096 UTF-8 bytes, not Python characters.
    MAX_MESSAGE_LENGTH = 2800

    def __init__(self, bot_token, chat_id, dry_run=True):
        self.bot_token = bot_token
        self.chat_id = chat_id
        self.dry_run = dry_run
        self._last_request_at = 0.0

    def _send(self, session, url, text):
        elapsed = time.monotonic() - self._last_request_at
        if elapsed < self.MIN_REQUEST_INTERVAL:
            time.sleep(self.MIN_REQUEST_INTERVAL - elapsed)

        for attempt in range(4):
            try:
                response = session.post(
                    url,
                    json={
                        "chat_id": self.chat_id,
                        "text": text,
                        "disable_web_page_preview": False,
                    },
                    timeout=20,
                )
                self._last_request_at = time.monotonic()

                if response.status_code != 429:
                    if not response.ok:
                        try:
                            detail = response.json()
                        except ValueError:
                            detail = response.text[:1000]
                        raise requests.HTTPError(
                            f"Telegram API {response.status_code}: {detail}",
                            response=response,
                        )
                    return

                retry_after = 2
                try:
                    retry_after = int(
                        response.json().get("parameters", {}).get("retry_after", 2)
                    )
                except (ValueError, TypeError):
                    pass

                if attempt == 3:
                    response.raise_for_status()
                time.sleep(max(retry_after, 1))
            except requests.RequestException:
                if attempt == 3:
                    raise
                time.sleep(2 ** attempt)

    @staticmethod
    def _product_block(p):
        if not hasattr(p, "source_products"):
            return (
                f"📱 {p.model}\n\n"
                f"💰 بهترین قیمت: {p.best_price:,.0f}\n"
                f"🏪 فروشنده: {p.best_source}\n"
                f"📦 وضعیت: {p.best_stock}\n"
                f"🔗 {p.best_url}"
            )

        lines = [
            f"📱 {p.model}",
            f"🔎 تعداد گزینه‌های مقایسه: {len(p.source_products)}",
            "",
            "📋 محصولات مقایسه‌شده:",
        ]

        for i, sp in enumerate(p.source_products, 1):
            price = f"{float(sp.price):,.0f}" if sp.price is not None else "بدون قیمت"
            lines.append(f"{i}. {sp.source} | {price} | {sp.stock}")
            if sp.product_name:
                lines.append(f"   نام: {sp.product_name}")
            if sp.color:
                lines.append(f"   🎨 رنگ: {sp.color}")
            if sp.storage or sp.ram:
                specs = ' / '.join(x for x in [sp.storage, sp.ram] if x)
                lines.append(f"   ⚙️ مشخصات: {specs}")
            if sp.url:
                lines.append(f"   🔗 {sp.url}")

        lines.append("")
        if getattr(p, "variant_results", None):
            lines.append("🎨 نتیجه مقایسه رنگ‌به‌رنگ:")
            for key, result in p.variant_results.items():
                label = result["variant"] or "بدون رنگ مشخص"
                lines.append(f"\n🔹 {label}")
                for offer in result["offers"]:
                    marker = "✅" if (offer["source"] == result["source"] and float(offer["price"]) == float(result["price"])) else "▫️"
                    lines.append(f"{marker} {offer['source']}: {offer['price']:,.0f}")
                lines.append(f"🏆 انتخاب این رنگ: {result['source']} — {result['price']:,.0f}")
                if result.get("url"):
                    lines.append(f"🔗 {result['url']}")

            lines.extend([
                "",
                "🏆 نتیجه نهایی محصول:",
                f"💰 ارزان‌ترین Variant: {p.best_price:,.0f}",
                f"🏪 فروشنده: {p.best_source}",
                f"🔗 {p.best_url}",
            ])
        elif p.best_price is not None:
            lines.extend([
                "🏆 نتیجه نهایی مقایسه:",
                f"💰 کمترین قیمت معتبر: {p.best_price:,.0f}",
                f"🏪 فروشنده انتخاب‌شده: {p.best_source}",
                f"📦 وضعیت: {p.best_stock}",
                f"🔗 لینک انتخاب‌شده: {p.best_url}",
            ])
        else:
            lines.append("⚠️ نتیجه: هیچ قیمت معتبر و قابل انتخابی پیدا نشد.")

        return "\n".join(lines)

    @classmethod
    def _messages(cls, products):
        chunks = []
        current = []

        for p in products:
            if hasattr(p, "source_products") and not p.source_products:
                continue
            if p.best_price is None:
                continue

            text = cls._product_block(p)
            candidate = "\n\n────────────\n\n".join(current + [text])
            if current and len(candidate.encode("utf-8")) > cls.MAX_MESSAGE_LENGTH:
                chunks.append("\n\n────────────\n\n".join(current))
                current = [text]
            elif not current and len(text.encode("utf-8")) > cls.MAX_MESSAGE_LENGTH:
                # A single product can itself exceed Telegram's byte limit.
                # Split it safely on UTF-8 byte boundaries while preserving text.
                chunks.extend(cls._split_utf8(text))
                current = []
            else:
                current.append(text)

        if current:
            chunks.append("\n\n────────────\n\n".join(current))
        return chunks

    @classmethod
    def _split_utf8(cls, text):
        chunks = []
        current = ""
        for line in text.splitlines(True):
            candidate = current + line
            if current and len(candidate.encode("utf-8")) > cls.MAX_MESSAGE_LENGTH:
                chunks.append(current.rstrip("\n"))
                current = line
            elif not current and len(line.encode("utf-8")) > cls.MAX_MESSAGE_LENGTH:
                raw = line.encode("utf-8")
                start = 0
                while start < len(raw):
                    end = min(start + cls.MAX_MESSAGE_LENGTH, len(raw))
                    while end > start:
                        try:
                            part = raw[start:end].decode("utf-8")
                            break
                        except UnicodeDecodeError:
                            end -= 1
                    if end == start:
                        break
                    chunks.append(part)
                    start = end
                current = ""
            else:
                current = candidate
        if current:
            chunks.append(current.rstrip("\n"))
        return chunks

    def publish(self, products):
        if self.dry_run:
            return True

        url = f"https://api.telegram.org/bot{self.bot_token}/sendMessage"
        with requests.Session() as session:
            for text in self._messages(products):
                self._send(session, url, text)
        return True
