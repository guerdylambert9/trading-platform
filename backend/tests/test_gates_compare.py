from __future__ import annotations

from datetime import date

import pandas as pd
import pytest
from sqlalchemy.orm import Session

from tests.helpers import UNIVERSE
from trader import ledger
from trader.backtest import Gate1Criteria, evaluate_gate1, log_holdout_use
from trader.data.synthetic import SyntheticBarSource
from trader.db import init_db, make_engine
from trader.models import AIDecision
from trader.risk import RiskLimits
from trader.services.ab_compare import compare_ab
from trader.strategies import TrendFollowing


@pytest.fixture(scope="module")
def closes() -> pd.DataFrame:
    return SyntheticBarSource().get_closes(UNIVERSE, date(2015, 1, 1), date(2026, 11, 12))


def test_gate1_runs_every_check(closes):
    report = evaluate_gate1(closes, TrendFollowing(100), RiskLimits(), "SPY", "2023-01-01", universe=UNIVERSE)
    assert [c.name for c in report.checks] == [
        "beats_benchmark",
        "max_drawdown",
        "enough_trades",
        "robust_to_parameters",
        "survives_one_day_delay",
    ]
    assert report.passed == all(c.passed for c in report.checks)
    assert report.holdout["start"].startswith("2023-01")


def test_gate1_fails_impossible_criteria(closes):
    strict = Gate1Criteria(min_round_trips=1_000_000, max_drawdown_pct=0.0)
    report = evaluate_gate1(
        closes, TrendFollowing(100), RiskLimits(), "SPY", "2023-01-01", criteria=strict, universe=UNIVERSE
    )
    checks = {c.name: c.passed for c in report.checks}
    assert not report.passed and not checks["enough_trades"] and not checks["max_drawdown"]


def test_gate1_rejects_a_holdout_after_the_data(closes):
    with pytest.raises(ValueError):
        evaluate_gate1(closes, TrendFollowing(100), RiskLimits(), "SPY", "2030-01-01", universe=UNIVERSE)


def test_holdout_log_counts_earlier_looks(closes, tmp_path):
    report = evaluate_gate1(closes, TrendFollowing(100), RiskLimits(), "SPY", "2024-01-01", universe=UNIVERSE)
    assert log_holdout_use(tmp_path, report) == 0
    assert log_holdout_use(tmp_path, report) == 1


def ledger_db(path, label, equities, ai_cost=0.0) -> str:
    url = f"sqlite:///{path}"
    engine = make_engine(url)
    init_db(engine)
    days = pd.bdate_range("2026-06-01", periods=len(equities))
    with Session(engine) as session:
        for day, value in zip(days, equities, strict=True):
            ledger.record_equity(session, day.date(), value, value, None, label)
        if ai_cost:
            ledger.record_ai_decision(
                session,
                AIDecision(symbol="SPY", as_of=days[1].date(), rating="hold", cost_usd=ai_cost),
                label,
            )
        session.commit()
    engine.dispose()
    return url


def test_compare_ab_charges_ai_costs(tmp_path):
    a = ledger_db(tmp_path / "a.db", "A", [100_000, 100_500, 101_000, 101_500])
    b = ledger_db(tmp_path / "b.db", "B", [100_000, 100_800, 101_600, 102_400])
    assert compare_ab(a, b, min_days=4)["passed"] is True

    pricey = ledger_db(tmp_path / "c.db", "B", [100_000, 100_800, 101_600, 102_400], ai_cost=2_000)
    result = compare_ab(a, pricey, min_days=4)
    assert result["rules_plus_ai"]["ai_cost_usd"] == pytest.approx(2_000)
    assert result["passed"] is False


def test_compare_ab_needs_twelve_weeks_by_default(tmp_path):
    a = ledger_db(tmp_path / "a.db", "A", [100_000, 100_500, 101_000, 101_500])
    b = ledger_db(tmp_path / "b.db", "B", [100_000, 100_800, 101_600, 102_400])
    result = compare_ab(a, b)
    assert result["enough_days"] is False and result["passed"] is False


def test_compare_ab_needs_overlapping_history(tmp_path):
    a = ledger_db(tmp_path / "a.db", "A", [100_000])
    b = ledger_db(tmp_path / "b.db", "B", [100_000])
    with pytest.raises(ValueError):
        compare_ab(a, b)
