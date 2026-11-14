"""Daily bars from Alpaca's market data API.

The free Basic plan serves consolidated (SIP) history as long as the request ends at least
15 minutes in the past, which suits end-of-day strategies. Closes are split- and
dividend-adjusted so backtests aren't distorted by corporate actions.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, date, datetime, time, timedelta

import pandas as pd
from alpaca.data.enums import Adjustment, DataFeed
from alpaca.data.historical import StockHistoricalDataClient
from alpaca.data.requests import StockBarsRequest
from alpaca.data.timeframe import TimeFrame

from trader.data.base import clean_closes
from trader.utils import NY


class AlpacaBarSource:
    def __init__(self, api_key: str, secret_key: str, feed: str = "sip") -> None:
        if not api_key or not secret_key:
            raise ValueError("Set ALPACA_API_KEY and ALPACA_SECRET_KEY to use DATA_SOURCE=alpaca.")
        self.client = StockHistoricalDataClient(api_key, secret_key)
        self.feed = DataFeed(feed)

    def get_closes(self, symbols: Sequence[str], start: date, end: date) -> pd.DataFrame:
        start_at = datetime.combine(start, time(0, 0), tzinfo=NY)
        end_at = min(
            datetime.combine(end, time(23, 59), tzinfo=NY),
            datetime.now(UTC) - timedelta(minutes=16),
        )
        request = StockBarsRequest(
            symbol_or_symbols=list(symbols),
            timeframe=TimeFrame.Day,
            start=start_at,
            end=end_at,
            adjustment=Adjustment.ALL,
            feed=self.feed,
        )
        bars = self.client.get_stock_bars(request).df
        if bars.empty:
            return pd.DataFrame(columns=list(symbols), dtype=float)
        closes = bars["close"].unstack(level=0)
        return clean_closes(closes, symbols)
