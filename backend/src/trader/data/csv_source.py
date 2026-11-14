"""Closes from a local CSV (date column + one column per symbol), e.g. from `trader fetch-data`."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import date
from pathlib import Path

import pandas as pd

from trader.data.base import clean_closes


class CsvBarSource:
    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self._frame: pd.DataFrame | None = None

    def _load(self) -> pd.DataFrame:
        if self._frame is None:
            if not self.path.exists():
                raise FileNotFoundError(f"{self.path} not found. Run `trader fetch-data` first.")
            raw = pd.read_csv(self.path, index_col=0, parse_dates=True)
            self._frame = clean_closes(raw, list(raw.columns))
        return self._frame

    def get_closes(self, symbols: Sequence[str], start: date, end: date) -> pd.DataFrame:
        frame = self._load()
        missing = [symbol for symbol in symbols if symbol not in frame.columns]
        if missing:
            raise ValueError(f"{self.path} has no column for: {', '.join(missing)}")
        return frame.loc[pd.Timestamp(start) : pd.Timestamp(end), list(symbols)]


def save_closes(frame: pd.DataFrame, path: str | Path) -> Path:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    frame.to_csv(target, index_label="date", float_format="%.6f")
    return target
