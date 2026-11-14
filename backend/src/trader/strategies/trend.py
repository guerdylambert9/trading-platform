"""Trend following: hold each asset while its close is above its N-day moving average."""

from __future__ import annotations

from typing import Any

import pandas as pd

from trader.strategies.base import Strategy


class TrendFollowing(Strategy):
    """Equal weight (1/N of the universe) in every asset that closes above its moving average.

    A classic time-series trend rule: in cash for assets in a downtrend. With a 10-asset
    universe each holding targets 10% of equity.
    """

    name = "trend"

    def __init__(self, window: int = 200) -> None:
        if window < 2:
            raise ValueError("window must be at least 2")
        self.window = int(window)

    @property
    def lookback_days(self) -> int:
        return self.window

    def target_weights(self, closes: pd.DataFrame) -> pd.DataFrame:
        average = closes.rolling(self.window, min_periods=self.window).mean()
        in_trend = (closes > average) & average.notna()
        count = max(len(closes.columns), 1)
        return in_trend.astype(float) / count

    def params(self) -> dict[str, Any]:
        return {"window": self.window}

    def variants(self) -> list[Strategy]:
        return [TrendFollowing(round(self.window * 0.8)), TrendFollowing(round(self.window * 1.2))]
