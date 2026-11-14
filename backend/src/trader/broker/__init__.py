from __future__ import annotations

from collections.abc import Callable
from typing import TYPE_CHECKING

from trader.broker.base import Broker
from trader.broker.fake import FakeBroker

if TYPE_CHECKING:
    from trader.config import Settings


def get_broker(settings: Settings, price_source: Callable[[str], float | None] | None = None) -> Broker:
    from trader.config import BrokerKind

    if settings.broker == BrokerKind.ALPACA:
        from trader.broker.alpaca_broker import AlpacaBroker

        return AlpacaBroker(
            settings.alpaca_api_key,
            settings.alpaca_secret_key,
            paper=not settings.is_live,
            latest_feed=settings.alpaca_latest_feed,
        )
    return FakeBroker(
        state_path=settings.fake_broker_state or None, always_open=True, price_source=price_source
    )


__all__ = ["Broker", "FakeBroker", "get_broker"]
