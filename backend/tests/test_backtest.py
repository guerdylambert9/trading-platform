from __future__ import annotations

from datetime import date

import numpy as np
import pandas as pd
import pytest

from tests.helpers import UNIVERSE, ConstantWeights
from trader.backtest import BacktestConfig, backtest_report, performance, run_backtest
from trader.backtest.metrics import limit_breaches
from trader.data.synthetic import SyntheticBarSource
from trader.risk.limits import RiskLimits
from trader.strategies import TrendFollowing

ALL_IN = RiskLimits(max_position_pct=100, risk_per_trade_pct=100, stop_loss_pct=0, entry_limit_buffer_pct=0)


def synthetic() -> pd.DataFrame:
    return SyntheticBarSource().get_closes(UNIVERSE, date(2014, 1, 1), date(2022, 12, 30))


def test_full_allocation_without_costs_tracks_buy_and_hold():
    closes = synthetic()[["SPY"]]
    result = run_backtest(closes, ConstantWeights({"SPY": 1.0}), ALL_IN, BacktestConfig(cost_bps=0))
    expected = 100_000 * closes["SPY"].iloc[-1] / closes["SPY"].iloc[0]
    assert result.equity.iloc[-1] == pytest.approx(expected, rel=0.01)
    assert len(result.fills) == 1


def test_costs_reduce_returns():
    closes = synthetic()
    free = run_backtest(closes, TrendFollowing(100), RiskLimits(), BacktestConfig(cost_bps=0), UNIVERSE)
    costly = run_backtest(closes, TrendFollowing(100), RiskLimits(), BacktestConfig(cost_bps=25), UNIVERSE)
    assert costly.equity.iloc[-1] < free.equity.iloc[-1]


def test_lag_two_trades_one_day_later():
    closes = synthetic()[["SPY"]]
    lag1 = run_backtest(closes, ConstantWeights({"SPY": 0.5}), RiskLimits(), BacktestConfig(lag=1))
    lag2 = run_backtest(closes, ConstantWeights({"SPY": 0.5}), RiskLimits(), BacktestConfig(lag=2))
    assert lag1.fills["date"].iloc[0] == closes.index[0]
    assert lag2.fills["date"].iloc[0] == closes.index[1]


def test_stop_loss_exits_and_does_not_reenter_the_same_day():
    index = pd.bdate_range("2025-01-01", periods=12)
    prices = [100, 100, 100, 100, 100, 85, 85, 86, 87, 88, 89, 90]
    closes = pd.DataFrame({"SPY": prices}, index=index, dtype=float)
    result = run_backtest(closes, ConstantWeights({"SPY": 0.1}), RiskLimits(), BacktestConfig(cost_bps=0))
    first = result.trades.iloc[0]
    assert first["exit_reason"] == "stop"
    assert first["exit_date"] == index[5]
    buys = result.fills[result.fills["side"] == "buy"]["date"].tolist()
    assert index[5] not in buys and index[6] in buys


def test_entries_respect_the_position_cap():
    closes = synthetic()
    result = run_backtest(
        closes, ConstantWeights(dict.fromkeys(UNIVERSE, 0.5)), RiskLimits(), BacktestConfig()
    )
    buys = result.fills[result.fills["side"] == "buy"]
    equity_then = result.equity.loc[buys["date"]].to_numpy()
    assert (buys["notional"].to_numpy() <= 0.10 * equity_then * 1.001).all()
    assert result.open_positions.max() <= RiskLimits().max_open_positions


def test_performance_on_a_known_series():
    equity = pd.Series([100.0, 120.0, 90.0, 135.0], index=pd.bdate_range("2024-01-01", periods=4))
    metrics = performance(equity)
    assert metrics["total_return"] == pytest.approx(0.35)
    assert metrics["max_drawdown"] == pytest.approx(-0.25)
    assert metrics["days"] == 3


def test_performance_handles_too_little_data():
    metrics = performance(pd.Series([100.0], index=pd.bdate_range("2024-01-01", periods=1)))
    assert metrics["cagr"] is None and metrics["calmar"] is None


def test_report_compares_against_the_benchmark():
    closes = synthetic()
    result = run_backtest(closes, TrendFollowing(100), RiskLimits(), BacktestConfig(), UNIVERSE)
    report = backtest_report(result, closes, "SPY", RiskLimits(), start=pd.Timestamp("2016-01-01"))
    assert report["window"]["start"] == "2016-01-01"
    assert report["benchmark"]["symbol"] == "SPY"
    assert report["trades"]["round_trips"] > 0
    assert 0 <= report["avg_exposure"] <= 1


def test_limit_breaches_count_episodes_not_days():
    values = [100, 89, 88, 95, 101, 90, 89, 100]
    equity = pd.Series(values, index=pd.bdate_range("2024-01-01", periods=len(values)), dtype=float)
    breaches = limit_breaches(equity, max_drawdown_pct=10, daily_loss_pct=5)
    assert breaches["drawdown_limit_breaches"] == 2
    assert breaches["daily_loss_limit_days"] == 2


def test_bad_config_is_rejected():
    with pytest.raises(ValueError):
        BacktestConfig(lag=0)
    with pytest.raises(ValueError):
        run_backtest(
            pd.DataFrame({"X": [1.0, 2.0]}, index=pd.bdate_range("2024-01-01", periods=2)),
            TrendFollowing(2),
            RiskLimits(),
            universe=["SPY"],
        )


def test_backtest_is_deterministic():
    closes = synthetic()
    a = run_backtest(closes, TrendFollowing(100), RiskLimits(), BacktestConfig(), UNIVERSE)
    b = run_backtest(closes, TrendFollowing(100), RiskLimits(), BacktestConfig(), UNIVERSE)
    assert np.array_equal(a.equity.to_numpy(), b.equity.to_numpy())
