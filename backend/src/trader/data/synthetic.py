"""Deterministic made-up prices for the demo and the tests. Not market data."""

from __future__ import annotations

import zlib
from collections.abc import Sequence
from datetime import date

import numpy as np
import pandas as pd


class SyntheticBarSource:
    """Random-walk prices with trending regimes, the same on every run for the same seed.

    The full series is generated once from a fixed start date, so the price on any given day
    never depends on which window you ask for.
    """

    EPOCH = pd.Timestamp("2010-01-04")
    HORIZON = pd.Timestamp("2035-12-31")

    def __init__(self, seed: int = 7) -> None:
        self.seed = seed
        self._dates = pd.bdate_range(self.EPOCH, self.HORIZON)
        self._market = self._market_returns()
        self._cache: dict[str, pd.Series] = {}

    def _regime_drift(self, rng: np.random.Generator, size: int, scale: float) -> np.ndarray:
        drift = np.empty(size)
        position = 0
        while position < size:
            length = int(rng.integers(120, 320))
            drift[position : position + length] = rng.uniform(-scale, scale) + scale * 0.1
            position += length
        return drift

    def _market_returns(self) -> np.ndarray:
        rng = np.random.default_rng(self.seed)
        size = len(self._dates)
        return self._regime_drift(rng, size, 0.0009) + rng.normal(0.0, 0.009, size)

    def _series(self, symbol: str) -> pd.Series:
        if symbol not in self._cache:
            rng = np.random.default_rng([self.seed, zlib.crc32(symbol.encode())])
            size = len(self._dates)
            beta = rng.uniform(0.2, 1.3)
            own = self._regime_drift(rng, size, 0.0006) + rng.normal(0.0, rng.uniform(0.004, 0.012), size)
            returns = beta * self._market + own
            start_price = rng.uniform(40, 400)
            self._cache[symbol] = pd.Series(
                start_price * np.exp(np.cumsum(returns)), index=self._dates, name=symbol
            )
        return self._cache[symbol]

    def get_closes(self, symbols: Sequence[str], start: date, end: date) -> pd.DataFrame:
        frame = pd.DataFrame({symbol: self._series(symbol) for symbol in symbols})
        return frame.loc[pd.Timestamp(start) : pd.Timestamp(end)]
