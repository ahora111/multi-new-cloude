from types import SimpleNamespace

from destinations.telegram import TelegramDestination


def product(model="iPhone 16"):
    return SimpleNamespace(
        model=model,
        best_price=44000000,
        best_source="demo",
        best_stock="IN_STOCK",
        best_url="https://example.com",
    )


def test_telegram_messages_are_chunked():
    products = [product(f"Product {i}") for i in range(100)]
    messages = TelegramDestination._messages(products)
    assert messages
    assert all(len(message) <= 4096 for message in messages)


def test_telegram_skips_products_without_price():
    p = product()
    p.best_price = None
    assert TelegramDestination._messages([p]) == []


def test_telegram_chunk_limit_is_utf8_bytes():
    p = product('محصول تست')
    # Force a single large Persian block; character count can be below 4096
    # while UTF-8 byte count is above Telegram's 4096-byte limit.
    p.model = 'محصول ' + ('آ' * 1900)
    messages = TelegramDestination._messages([p])
    assert messages
    assert all(len(message.encode('utf-8')) <= 4096 for message in messages)
