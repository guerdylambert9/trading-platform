from __future__ import annotations

from datetime import date, timedelta

import numpy as np
import pandas as pd
import pytest

from tests.helpers import TODAY, UNIVERSE, at, make_ctx, make_settings
from trader import ledger
from trader.backtest import BacktestConfig
from trader.backtest.engine import run_backtest
from trader.data.synthetic import SyntheticBarSource
from trader.db import ReconciliationRow
from trader.risk.limits import RiskLimits
from trader.services import killswitch
from trader.services.gates import (
    Gate4Criteria,
    evaluate_gate2,
    evaluate_gate4,
    recent_weekdays,
    rolling_ranges,
    window_stats,
)
from trader.strategies import get_strategy


def checks_by_name(report):
    return {check.name: check for check in report.checks}


def add_checks(session, days, bad=()):
    for day in days:
        session.add(
            ReconciliationRow(
                ts=at(day, 16, 30),
                ok=day not in bad,
                mismatches=[] if day not in bad else [{"kind": "unknown_order"}],
                account_label="A",
            )
        )
    session.flush()


# ---------------------------------------------------------------- Gate 2


def test_recent_weekdays_skips_weekends():
    days = recent_weekdays(date(2026, 11, 16), 3)  # a Monday
    assert days == [date(2026, 11, 12), date(2026, 11, 13), date(2026, 11, 16)]


def test_gate2_passes_with_ten_clean_weekdays_and_a_tested_kill_switch():
    ctx = make_ctx()
    paper = make_settings(broker="alpaca")
    with ctx.session() as session:
        add_checks(session, recent_weekdays(TODAY, 10))
        killswitch.engage(ctx, session, reason="drill", by="test")
        killswitch.release(ctx, session, by="test")
        report = evaluate_gate2(session, paper, TODAY)
    assert report.passed, [c.detail for c in report.checks]
    assert set(checks_by_name(report)) == {
        "paper_account",
        "clean_broker_checks",
        "recent",
        "kill_switch_tested",
    }


def test_gate2_names_missing_and_failed_days_and_needs_the_kill_switch_drill():
    ctx = make_ctx()
    paper = make_settings(broker="alpaca")
    window = recent_weekdays(TODAY, 10)
    skipped, failed = window[2], window[5]
    with ctx.session() as session:
        add_checks(session, [day for day in window if day != skipped], bad={failed})
        report = evaluate_gate2(session, paper, TODAY)
    checks = checks_by_name(report)
    assert not report.passed
    assert not checks["clean_broker_checks"].passed
    assert f"{skipped:%b} {skipped.day}" in checks["clean_broker_checks"].detail
    assert f"{failed:%b} {failed.day}" in checks["clean_broker_checks"].detail
    assert not checks["kill_switch_tested"].passed
    assert checks["recent"].passed


def test_gate2_needs_current_results_and_a_released_kill_switch():
    ctx = make_ctx()
    paper = make_settings(broker="alpaca")
    with ctx.session() as session:
        add_checks(session, recent_weekdays(TODAY - timedelta(days=21), 10))
        killswitch.engage(ctx, session, reason="drill", by="test")
        report = evaluate_gate2(session, paper, TODAY)
    checks = checks_by_name(report)
    assert checks["clean_broker_checks"].passed
    assert not checks["recent"].passed
    assert not checks["kill_switch_tested"].passed
    assert "not released" in checks["kill_switch_tested"].detail


def test_gate2_rejects_the_demo_broker_and_live_mode():
    ctx = make_ctx()
    with ctx.session() as session:
        add_checks(session, recent_weekdays(TODAY, 10))
        demo = evaluate_gate2(session, make_settings(), TODAY)
        live = evaluate_gate2(
            session, make_settings(broker="alpaca", trading_mode="live", live_trading_confirmed=True), TODAY
        )
    assert not checks_by_name(demo)["paper_account"].passed
    assert not checks_by_name(live)["paper_account"].passed


# ---------------------------------------------------------------- Gate 4


def test_window_stats_and_rolling_ranges():
    path = [100.0, 110.0, 99.0, 121.0]
    ret, drawdown = window_stats(path)
    assert ret == pytest.approx(0.21)
    assert drawdown == pytest.approx(0.1)
    returns, drawdowns = rolling_ranges(pd.Series(path), 2)
    assert returns == pytest.approx([-0.01, 0.1])
    assert drawdowns == pytest.approx([0.1, 0.1])
    assert rolling_ranges(pd.Series(path), 5)[0].size == 0


@pytest.fixture(scope="module")
def history():
    end = date(2025, 12, 31)
    closes = SyntheticBarSource().get_closes(UNIVERSE, date(2019, 1, 1), end)
    return closes, end


def record_path(session, start: date, values):
    day = start
    for value in values:
        while day.weekday() >= 5:
            day += timedelta(days=1)
        ledger.record_equity(session, day, float(value), float(value), None, "A")
        day += timedelta(days=1)
    session.flush()


def run_gate4(path, history, calls=None):
    closes, end = history
    ctx = make_ctx()
    paper = make_settings(broker="alpaca")
    strategy = get_strategy("trend")

    def closes_until(day):
        if calls is not None:
            calls.append(day)
        return closes.loc[: pd.Timestamp(day)]

    with ctx.session() as session:
        record_path(session, end + timedelta(days=1), path)
        return evaluate_gate4(
            session, paper, closes_until, strategy, RiskLimits.from_settings(paper), Gate4Criteria(weeks=12)
        )


def test_gate4_passes_when_paper_matches_the_backtest(history):
    closes, end = history
    paper = make_settings(broker="alpaca")
    reference = run_backtest(
        closes, get_strategy("trend"), RiskLimits.from_settings(paper), BacktestConfig(), UNIVERSE
    )
    returns, _ = rolling_ranges(reference.equity, 60)
    typical = float(np.median(returns))
    path = np.linspace(100_000, 100_000 * (1 + typical), 61)

    report = run_gate4(path, history)
    assert report.passed, [c.detail for c in report.checks]
    assert report.details["backtest_windows"] >= 250


def test_gate4_fails_far_outside_the_ranges(history):
    path = np.linspace(100_000, 60_000, 61)
    report = run_gate4(path, history)
    checks = checks_by_name(report)
    assert not report.passed
    assert not checks["return_in_range"].passed
    assert not checks["drawdown_in_range"].passed


def test_gate4_waits_for_twelve_weeks_without_loading_prices(history):
    calls: list[date] = []
    report = run_gate4(np.full(30, 100_000.0), history, calls)
    assert not checks_by_name(report)["enough_history"].passed
    assert calls == []


# ---------------------------------------------------------------- Gate 5


def ledger_url(path, label, values) -> str:
    from sqlalchemy.orm import Session

    from trader.db import init_db, make_engine

    url = f"sqlite:///{path}"
    engine = make_engine(url)
    init_db(engine)
    with Session(engine) as session:
        for day, value in zip(pd.bdate_range("2026-01-05", periods=len(values)), values, strict=True):
            ledger.record_equity(session, day.date(), float(value), float(value), None, label)
        session.commit()
    engine.dispose()
    return url


def live_settings(url):
    return make_settings(
        broker="alpaca", trading_mode="live", live_trading_confirmed=True, database_url=url, account_label="L"
    )


def test_gate5_passes_when_live_tracks_paper(tmp_path):
    from trader.services.gates import evaluate_gate5

    rng = np.random.default_rng(3)
    paper_path = 100_000 * np.cumprod(1 + rng.normal(0.0004, 0.008, 70))
    live_path = 5_000 * paper_path / paper_path[0] * np.cumprod(1 + rng.normal(0, 0.0005, 70))
    paper_url = ledger_url(tmp_path / "paper.db", "A", paper_path)
    live_url = ledger_url(tmp_path / "live.db", "L", live_path)
    report = evaluate_gate5(live_settings(live_url), paper_url)
    assert report.passed, [c.detail for c in report.checks]


def test_gate5_fails_when_live_drifts_or_is_too_short(tmp_path):
    from trader.services.gates import evaluate_gate5

    rng = np.random.default_rng(4)
    paper_path = 100_000 * np.cumprod(1 + rng.normal(0.0004, 0.008, 70))
    drifting = 5_000 * np.cumprod(1 + rng.normal(-0.002, 0.008, 70))
    paper_url = ledger_url(tmp_path / "paper.db", "A", paper_path)
    report = evaluate_gate5(live_settings(ledger_url(tmp_path / "live.db", "L", drifting)), paper_url)
    checks = checks_by_name(report)
    assert not report.passed
    assert not checks["return_gap"].passed and not checks["daily_tracking"].passed

    short = evaluate_gate5(live_settings(ledger_url(tmp_path / "short.db", "L", paper_path[:20])), paper_url)
    assert not checks_by_name(short)["enough_days"].passed
    paper_mode = evaluate_gate5(make_settings(database_url=paper_url, account_label="A"), paper_url)
    assert not checks_by_name(paper_mode)["live_account"].passed
