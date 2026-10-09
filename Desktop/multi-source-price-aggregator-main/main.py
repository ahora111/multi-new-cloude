import argparse
import os

from config.settings import settings
from core.models import SourceProduct
from core.pipeline import Pipeline
from destinations.json_destination import JsonDestination
from destinations.telegram import TelegramDestination
from utils.logging import get_logger

log = get_logger('main')


def build_sources(demo=False):
    if demo:
        from sources.demo import DemoSource
        return [DemoSource([
            SourceProduct(
                source='demo', source_product_id='demo-1',
                brand='Apple', product_name='Apple iPhone 16 128GB Black',
                storage='128GB', color='Black', price=45000000,
                stock='IN_STOCK', url='https://example.com/demo-1',
            ),
            SourceProduct(
                source='demo', source_product_id='demo-2',
                brand='Apple', product_name='iPhone 16 128GB Black',
                storage='128GB', color='Black', price=44000000,
                stock='IN_STOCK', url='https://example.com/demo-2',
            ),
        ])]

    sources = []
    if os.getenv('EWAYS_ENABLED', 'true').lower() == 'true':
        from sources.eways import EwaysSource
        sources.append(EwaysSource())
    if os.getenv('HAMRAHTEL_ENABLED', 'true').lower() == 'true':
        from sources.hamrahtel import HamrahtelSource
        sources.append(HamrahtelSource())
    return sources


def build_destinations():
    destinations = []
    if os.getenv('JSON_DESTINATION_ENABLED', 'true').lower() == 'true':
        destinations.append(JsonDestination(os.getenv('OUTPUT_JSON', 'data/output.json')))
    if os.getenv('TELEGRAM_ENABLED', 'false').lower() == 'true':
        token = os.getenv('TELEGRAM_BOT_TOKEN') or os.getenv('TELEGRAM_TOKEN')
        chat = os.getenv('TELEGRAM_CHAT_ID')
        if not token or not chat:
            raise RuntimeError('TELEGRAM_ENABLED=true but Telegram credentials are missing')
        destinations.append(TelegramDestination(token, chat, dry_run=settings.dry_run))
    return destinations


def main():
    parser = argparse.ArgumentParser(description='Multi-source product price aggregator')
    parser.add_argument('--demo', action='store_true', help='Run the pipeline with local demo data')
    args = parser.parse_args()

    sources = build_sources(demo=args.demo)
    destinations = build_destinations()
    if not sources:
        raise RuntimeError('No source enabled')
    summary = Pipeline(sources, destinations).run()
    print(summary.to_text())


if __name__ == '__main__':
    main()
