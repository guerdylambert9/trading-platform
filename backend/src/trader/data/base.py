"""Price data interface: daily closes as a wide table (one column per symbol)."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import date
from typing import Protocol

import pandas as pd

from trader.utils import NY


class BarSource(Protocol):
    def get_closes(self, symbols: Sequence[str], start: date, end: date) -> pd.DataFrame:
        """Split- and dividend-adjusted daily closes, index = trading dates (tz-naive)."""
        ...


def clean_closes(frame: pd.DataFrame, symbols: Sequence[str]) -> pd.DataFrame:
    index = pd.DatetimeIndex(pd.to_datetime(frame.index))
    if index.tz is not None:
        index = index.tz_convert(NY).tz_localize(None)
    cleaned = frame.copy()
    cleaned.index = index.normalize()
    cleaned = cleaned[~cleaned.index.duplicated(keep="last")].sort_index()
    columns = [symbol for symbol in symbols if symbol in cleaned.columns]
    return cleaned[columns].astype(float).dropna(how="all")


class FrameBarSource:
    """Serve closes from an in-memory DataFrame (tests, notebooks, replays)."""

    def __init__(self, frame: pd.DataFrame) -> None:
        self.frame = clean_closes(frame, list(frame.columns))

    def get_closes(self, symbols: Sequence[str], start: date, end: date) -> pd.DataFrame:
        missing = [symbol for symbol in symbols if symbol not in self.frame.columns]
        if missing:
            raise ValueError(f"No price data for: {', '.join(missing)}")
        return self.frame.loc[pd.Timestamp(start) : pd.Timestamp(end), list(symbols)]
