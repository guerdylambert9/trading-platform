"""Strategy interface. A strategy is a pure function of past closes."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

import pandas as pd


class Strategy(ABC):
    name: str = "base"

    @property
    @abstractmethod
    def lookback_days(self) -> int:
        """Trading days of history needed before the first valid signal."""

    @abstractmethod
    def target_weights(self, closes: pd.DataFrame) -> pd.DataFrame:
        """Target portfolio weights, one row per day and one column per symbol.

        Row t may only use closes up to and including t (decided after that close).
        Weights are in [0, 1] and each row sums to at most 1; the rest is cash.
        """

    @abstractmethod
    def params(self) -> dict[str, Any]:
        """The parameters that define this instance."""

    @abstractmethod
    def variants(self) -> list[Strategy]:
        """The same strategy with its parameters moved about 20% each way (Gate 1 robustness)."""

    def describe(self) -> dict[str, Any]:
        return {"name": self.name, **self.params()}

    def history_days(self) -> int:
        """Calendar days of history the live pipeline fetches so its signals match the backtest."""
        return int(self.lookback_days * 1.5) + 45

    def __repr__(self) -> str:
        args = ", ".join(f"{k}={v}" for k, v in self.params().items())
        return f"{type(self).__name__}({args})"
