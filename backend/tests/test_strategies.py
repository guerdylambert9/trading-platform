from __future__ import annotations

from datetime import date

import numpy as np
import pandas as pd
import pytest

from tests.helpers import UNIVERSE, trending_frame
from trader.data.synthetic import SyntheticBarSource
from trader.strategies import Momentum, TrendFollowing, get_strategy


def synthetic(start: str = "2014-01-01", end: str = "2026-11-12") -> pd.DataFrame:
    return SyntheticBarSource().get_closes(UNIVERSE, date.fromisoformat(start), date.fromisoformat(end))


def test_trend_holds_assets_above_their_average():
    weights = TrendFollowing(200).target_weights(trending_frame())
    last = weights.iloc[-1]
    for symbol in ("SPY", "QQQ", "GLD"):
        assert last[symbol] == pytest.approx(1 / 6)
    for symbol in ("EFA", "TLT"):
        assert last[symbol] == 0.0


def test_trend_waits_for_a_full_window():
    weights = TrendFollowing(200).target_weights(trending_frame())
    assert (weights.iloc[:199] == 0).all().all()
    assert weights.iloc[199:].sum(axis=1).gt(0).all()


def test_momentum_picks_top_n_with_positive_returns_and_holds_for_the_month():
    index = pd.bdate_range("2024-01-01", periods=400)
    t = np.arange(400, dtype=float)
    frame = pd.DataFrame(
        {"A": 100 * 1.002**t, "B": 100 * 1.001**t, "C": 100 * 1.0005**t, "D": 100 * 0.999**t},
        index=index,
    )
    weights = Momentum(lookback=100, skip=5, top_n=2).target_weights(frame)
    last = weights.iloc[-1]
    assert last["A"] == pytest.approx(0.5) and last["B"] == pytest.approx(0.5)
    assert last["C"] == 0 and last["D"] == 0
    month = weights.loc[weights.index.to_period("M") == weights.index[-1].to_period("M")]
    assert (month.nunique() == 1).all()  # weights only change on the month's first trading day


@pytest.mark.parametrize("strategy", [TrendFollowing(50), Momentum(60, 5, 2)], ids=repr)
def test_no_lookahead_truncating_the_future_changes_nothing(strategy):
    closes = synthetic()
    full = strategy.target_weights(closes)
    for cut in ("2016-06-15", "2019-03-01", "2022-12-30", "2026-11-11"):
        truncated = strategy.target_weights(closes.loc[:cut])
        pd.testing.assert_frame_equal(full.loc[:cut], truncated)


@pytest.mark.parametrize("name", ["trend", "momentum"])
def test_weights_are_valid(name):
    weights = get_strategy(name).target_weights(synthetic())
    assert ((weights >= 0) & (weights <= 1)).all().all()
    assert (weights.sum(axis=1) <= 1 + 1e-9).all()
    assert not weights.isna().any().any()


def test_variants_move_parameters_about_twenty_percent():
    assert [v.window for v in TrendFollowing(200).variants()] == [160, 240]
    assert [v.lookback for v in Momentum(250).variants()] == [200, 300]


def test_unknown_strategy_is_rejected():
    with pytest.raises(ValueError, match="Unknown strategy"):
        get_strategy("moon")
