"""Relative momentum: each month, hold the top N assets by their 12-1 month return."""

from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd

from trader.strategies.base import Strategy


class Momentum(Strategy):
    """Rank assets by return from `lookback` to `skip` days ago; hold the top N with a positive return.

    Rebalances on the first trading day of each month, a date known without looking ahead.
    Each holding targets 1/top_n of equity, then the risk limits cap it.
    """

    name = "momentum"

    def __init__(self, lookback: int = 252, skip: int = 21, top_n: int = 3) -> None:
        if not 0 <= skip < lookback:
            raise ValueError("need 0 <= skip < lookback")
        if top_n < 1:
            raise ValueError("top_n must be at least 1")
        self.lookback = int(lookback)
        self.skip = int(skip)
        self.top_n = int(top_n)

    @property
    def lookback_days(self) -> int:
        return self.lookback + 1

    def history_days(self) -> int:
        # Extra room so at least one month start falls inside the fetched window.
        return super().history_days() + 45

    def target_weights(self, closes: pd.DataFrame) -> pd.DataFrame:
        momentum = closes.shift(self.skip) / closes.shift(self.lookback) - 1
        rank = momentum.rank(axis=1, ascending=False, method="first")
        chosen = (rank <= self.top_n) & (momentum > 0)
        weights = chosen.astype(float) / self.top_n

        months = np.asarray(closes.index.year * 12 + closes.index.month)
        month_start = np.r_[True, months[1:] != months[:-1]] if len(months) else np.array([], dtype=bool)
        weights.loc[~month_start, :] = np.nan
        return weights.ffill().fillna(0.0)

    def params(self) -> dict[str, Any]:
        return {"lookback": self.lookback, "skip": self.skip, "top_n": self.top_n}

    def variants(self) -> list[Strategy]:
        return [
            Momentum(round(self.lookback * 0.8), self.skip, self.top_n),
            Momentum(round(self.lookback * 1.2), self.skip, self.top_n),
        ]
