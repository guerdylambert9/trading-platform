"""Shared test fixtures: crafted prices, a controllable clock and a context with fakes."""

from __future__ import annotations

from datetime import UTC, date, datetime, time
from typing import Any

import numpy as np
import pandas as pd

from trader.broker.fake import FakeBroker
from trader.config import Settings
from trader.data.base import FrameBarSource
from trader.notify.telegram import LogNotifier
from trader.services.context import AppContext, build_context
from trader.strategies.base import Strategy
from trader.utils import NY

UNIVERSE = ["SPY", "QQQ", "IWM", "EFA", "TLT", "GLD"]
TODAY = date(2026, 11, 12)  # a Thursday


def at(day: date, hour: int, minute: int) -> datetime:
    """A New York wall-clock time, as UTC."""
    return datetime.combine(day, time(hour, minute), tzinfo=NY).astimezone(UTC)


class MutableClock:
    def __init__(self, moment: datetime) -> None:
        self.moment = moment

    def set(self, day: date, hour: int, minute: int) -> None:
        self.moment = at(day, hour, minute)

    def __call__(self) -> datetime:
        return self.moment


def trending_frame(end: date = TODAY, days: int = 320) -> pd.DataFrame:
    """SPY, QQQ and GLD trend up; EFA and TLT trend down; IWM wobbles sideways."""
    index = pd.bdate_range(end=pd.Timestamp(end), periods=days)
    t = np.arange(days, dtype=float)
    return pd.DataFrame(
        {
            "SPY": 400 + 0.5 * t,
            "QQQ": 300 + 0.6 * t,
            "IWM": 200 + 6 * np.sin(t / 9),
            "EFA": 80 - 0.05 * t,
            "TLT": 100 - 0.1 * t,
            "GLD": 180 + 0.2 * t,
        },
        index=index,
    )


class ConstantWeights(Strategy):
    """Same target weights every day (from day `start` on)."""

    name = "constant"

    def __init__(self, weights: dict[str, float]) -> None:
        self.weights = weights

    @property
    def lookback_days(self) -> int:
        return 1

    def target_weights(self, closes: pd.DataFrame) -> pd.DataFrame:
        return pd.DataFrame({c: float(self.weights.get(c, 0.0)) for c in closes.columns}, index=closes.index)

    def params(self) -> dict[str, Any]:
        return {"weights": self.weights}

    def variants(self) -> list[Strategy]:
        return [self]


class StartAfter(Strategy):
    """Wraps a strategy and holds cash before a given date."""

    def __init__(self, inner: Strategy, start: date) -> None:
        self.inner = inner
        self.start = pd.Timestamp(start)
        self.name = inner.name

    @property
    def lookback_days(self) -> int:
        return self.inner.lookback_days

    def target_weights(self, closes: pd.DataFrame) -> pd.DataFrame:
        weights = self.inner.target_weights(closes).copy()
        weights.loc[weights.index < self.start, :] = 0.0
        return weights

    def params(self) -> dict[str, Any]:
        return self.inner.params()

    def variants(self) -> list[Strategy]:
        return [StartAfter(v, self.start.date()) for v in self.inner.variants()]


def make_settings(**overrides: Any) -> Settings:
    values: dict[str, Any] = {
        "_env_file": None,
        "database_url": "sqlite+pysqlite:///:memory:",
        "universe": ",".join(UNIVERSE),
        "benchmark": "SPY",
        "broker": "fake",
        "data_source": "synthetic",
        "fake_broker_state": "",
        "dry_run": False,
        "telegram_bot_token": "",
        "telegram_chat_id": "",
        "api_token": "",
        "strategy": "trend",
    }
    values.update(overrides)
    return Settings(**values)


def make_ctx(
    frame: pd.DataFrame | None = None,
    clock: MutableClock | None = None,
    broker: FakeBroker | None = None,
    strategy: Strategy | None = None,
    researcher: Any = None,
    **settings: Any,
) -> AppContext:
    clock = clock or MutableClock(at(TODAY, 17, 15))
    broker = broker or FakeBroker(cash=100_000, now_fn=clock)
    return build_context(
        make_settings(**settings),
        broker=broker,
        bars=FrameBarSource(frame if frame is not None else trending_frame()),
        strategy=strategy,
        researcher=researcher,
        notifier=LogNotifier(),
        now_fn=clock,
    )
