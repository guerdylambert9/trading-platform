"""Backtest/live parity: the live path must make the same decisions the backtest assumed."""

from __future__ import annotations

from datetime import date, timedelta

import numpy as np
import pandas as pd
import pytest

from tests.helpers import UNIVERSE, MutableClock, StartAfter, at, make_ctx
from trader import ledger
from trader.backtest import BacktestConfig, run_backtest
from trader.data.synthetic import SyntheticBarSource
from trader.risk import RiskLimits
from trader.services.pipeline import run_nightly
from trader.services.replay import replay
from trader.strategies import Momentum, TrendFollowing
from trader.utils import local_date

END = date(2026, 11, 12)


@pytest.fixture(scope="module")
def closes() -> pd.DataFrame:
    return SyntheticBarSource().get_closes(UNIVERSE, date(2014, 1, 1), END)


@pytest.mark.parametrize("strategy", [TrendFollowing(), Momentum()], ids=repr)
def test_live_window_gives_the_same_targets_as_the_full_history(closes, strategy):
    full = strategy.target_weights(closes)
    for day in closes.index[-500::37]:
        start = day - pd.Timedelta(days=strategy.history_days())
        live = strategy.target_weights(closes.loc[start:day]).iloc[-1]
        np.testing.assert_allclose(
            live.to_numpy(), full.loc[day].to_numpy(), atol=1e-12, err_msg=str(day.date())
        )


def test_pipeline_records_the_backtest_targets(closes):
    strategy = TrendFollowing()
    expected = strategy.target_weights(closes)
    ctx = make_ctx(frame=closes, strategy=strategy, clock=MutableClock(at(END, 17, 15)))
    for day in (closes.index[-40].date(), closes.index[-1].date()):
        ctx.now_fn.set(day, 17, 15)
        run_nightly(ctx, as_of=day)
        with ctx.session() as session:
            recorded = {s.symbol: s.target_weight for s in ledger.latest_signals(session, ctx.label)}
        assert recorded == pytest.approx(expected.loc[pd.Timestamp(day)].to_dict())


def test_replayed_live_jobs_trade_like_the_lag_two_backtest(closes):
    """Signal after the close, fill the next day: the live jobs and a lag-2 backtest must agree."""
    start = closes.index[-180].date()
    # Stops and the account-level brakes are switched off so only the signal logic is compared.
    # risk_per_trade_pct is raised so a far-away stop doesn't shrink positions to a share or two.
    loose = {
        "stop_loss_pct": 50.0,
        "risk_per_trade_pct": 100.0,
        "max_gap_pct": 100.0,
        "daily_loss_limit_pct": 100.0,
        "max_drawdown_pct": 100.0,
    }
    strategy = TrendFollowing(60)

    ctx = make_ctx(frame=closes, strategy=strategy, **loose)
    replay(ctx, start, END)
    with ctx.session() as session:
        live = {
            (local_date(row.submitted_at), row.symbol, row.side)
            for row in ledger.list_proposals(session, ctx.label, limit=10_000)
            if row.submitted_at is not None
        }

    window = closes.loc[pd.Timestamp(start) - pd.Timedelta(days=strategy.history_days()) :]
    limits = RiskLimits(
        stop_loss_pct=50.0, risk_per_trade_pct=100.0, daily_loss_limit_pct=100.0, max_drawdown_pct=100.0
    )
    result = run_backtest(
        window, StartAfter(strategy, start), limits, BacktestConfig(cost_bps=0, lag=2), UNIVERSE
    )
    fills = result.fills[result.fills["date"] <= pd.Timestamp(END)]
    backtest = {(row.date.date(), row.symbol, row.side) for row in fills.itertuples()}

    assert live, "the replay should have traded"
    assert live == backtest
    assert start + timedelta(days=1) <= min(d for d, _, _ in live)
