"""Gates 2 and 4: forward checks on a paper account, read from its own ledger.

Gate 2 (after building the app): a clean broker check on each of the last ten weekdays, and
the kill switch engaged and released at least once.

Gate 4 (paper forward test): twelve weeks of paper results that sit inside the ranges the
backtest produced over windows of the same length before the paper test started.

Gate 5 (live with small money): three months of live results that track the paper account
running the same rules over the same days.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import asdict, dataclass
from datetime import date, timedelta

import numpy as np
import pandas as pd
from sqlalchemy import select
from sqlalchemy.orm import Session

from trader import ledger
from trader.backtest.engine import BacktestConfig, run_backtest
from trader.backtest.gates import Check, GateReport
from trader.config import BrokerKind, Settings
from trader.db import AuditRow, ReconciliationRow
from trader.risk.limits import RiskLimits
from trader.services import killswitch
from trader.services.ab_compare import load_ledger
from trader.strategies.base import Strategy
from trader.utils import local_date


def paper_account_check(settings: Settings) -> Check:
    if settings.broker != BrokerKind.ALPACA:
        return Check(
            "paper_account",
            False,
            "These records come from the demo broker. Run this gate on an Alpaca paper account "
            "(BROKER=alpaca, TRADING_MODE=paper).",
        )
    if settings.is_live:
        return Check("paper_account", False, "This gate checks paper trading, but TRADING_MODE is live.")
    return Check("paper_account", True, f"Alpaca paper account {settings.account_label}")


def recent_weekdays(end: date, count: int) -> list[date]:
    """The `count` weekdays ending on or before `end`, oldest first."""
    days: list[date] = []
    day = end
    while len(days) < count:
        if day.weekday() < 5:
            days.append(day)
        day -= timedelta(days=1)
    return sorted(days)


def _days(days: Sequence[date]) -> str:
    return ", ".join(f"{day:%b} {day.day}" for day in days)


# ---------------------------------------------------------------- Gate 2


@dataclass(frozen=True)
class Gate2Criteria:
    days: int = 10  # weekdays in a row with a clean broker check
    max_age_days: int = 4  # the newest check must be this recent


def evaluate_gate2(
    session: Session, settings: Settings, today: date, criteria: Gate2Criteria | None = None
) -> GateReport:
    criteria = criteria or Gate2Criteria()
    checks = [paper_account_check(settings)]

    rows = session.scalars(
        select(ReconciliationRow).where(ReconciliationRow.account_label == settings.account_label)
    ).all()
    clean_by_day: dict[date, bool] = {}
    for row in rows:
        day = local_date(row.ts, settings.timezone)
        clean_by_day[day] = clean_by_day.get(day, True) and bool(row.ok)

    if not clean_by_day:
        checks.append(
            Check(
                "clean_broker_checks",
                False,
                "No broker checks recorded yet. Run the scheduler on paper (trader serve --scheduler).",
            )
        )
        checks.append(Check("recent", False, "No broker checks recorded yet."))
    else:
        newest = max(clean_by_day)
        window = recent_weekdays(newest, criteria.days)
        missing = [day for day in window if day not in clean_by_day]
        failed = [day for day in window if clean_by_day.get(day) is False]
        span = f"the {criteria.days} weekdays from {_days([window[0]])} to {_days([window[-1]])}"
        if not missing and not failed:
            detail = f"A clean broker check on each of {span}."
        else:
            parts = []
            if missing:
                parts.append(f"no check on {_days(missing)}")
            if failed:
                parts.append(f"problems found on {_days(failed)}")
            detail = f"Over {span}: {'; '.join(parts)}."
        checks.append(Check("clean_broker_checks", not missing and not failed, detail))

        age = (today - newest).days
        checks.append(
            Check(
                "recent",
                age <= criteria.max_age_days,
                f"Newest check {_days([newest])}"
                + (
                    "."
                    if age <= criteria.max_age_days
                    else f", {age} days ago; the gate needs current results."
                ),
            )
        )

    events = session.scalars(
        select(AuditRow)
        .where(AuditRow.event.in_(["kill_switch_engaged", "kill_switch_released"]))
        .order_by(AuditRow.id)
    ).all()
    engaged = next((event for event in events if event.event == "kill_switch_engaged"), None)
    released = next(
        (e for e in events if e.event == "kill_switch_released" and engaged and e.id > engaged.id), None
    )
    still_engaged = killswitch.is_engaged(session)
    if engaged is None:
        detail = (
            "Never engaged. Engage it from the dashboard, confirm that pending entries were canceled "
            "and the stops stayed, then release it."
        )
    elif released is None or still_engaged:
        detail = "Engaged, but not released yet."
    else:
        tz = settings.timezone
        detail = (
            f"Engaged on {_days([local_date(engaged.ts, tz)])} "
            f"and released on {_days([local_date(released.ts, tz)])}."
        )
    checks.append(
        Check(
            "kill_switch_tested", engaged is not None and released is not None and not still_engaged, detail
        )
    )

    return GateReport(
        gate="gate2",
        strategy={"name": settings.strategy},
        passed=all(check.passed for check in checks),
        checks=checks,
        holdout={},
        criteria=asdict(criteria),
    )


# ---------------------------------------------------------------- Gate 4


@dataclass(frozen=True)
class Gate4Criteria:
    weeks: int = 12
    low_percentile: float = 5.0  # paper return must be at or above this percentile of backtest windows
    high_percentile: float = 95.0  # ...at or below this one; paper drawdown at or below it too
    min_windows: int = 250  # backtest windows needed for the ranges to mean something


def window_stats(values: Sequence[float]) -> tuple[float, float]:
    """Return and max drawdown (a positive fraction) of one equity path."""
    path = np.asarray(values, dtype=float)
    drawdown = -float(np.min(path / np.maximum.accumulate(path) - 1.0))
    return float(path[-1] / path[0] - 1.0), drawdown


def rolling_ranges(equity: pd.Series, days: int) -> tuple[np.ndarray, np.ndarray]:
    """Return and max drawdown of every window of `days` trading days in an equity curve."""
    values = equity.to_numpy(dtype=float)
    count = len(values) - days
    if count <= 0:
        return np.array([]), np.array([])
    returns = values[days:] / values[:-days] - 1.0
    drawdowns = np.empty(count)
    for start in range(count):
        drawdowns[start] = window_stats(values[start : start + days + 1])[1]
    return returns, drawdowns


def evaluate_gate4(
    session: Session,
    settings: Settings,
    closes_until: Callable[[date], pd.DataFrame],
    strategy: Strategy,
    limits: RiskLimits,
    criteria: Gate4Criteria | None = None,
    config: BacktestConfig | None = None,
) -> GateReport:
    """closes_until(day) returns daily closes up to and including `day`; it is only called when
    the paper account has enough history to judge."""
    criteria = criteria or Gate4Criteria()
    days = criteria.weeks * 5
    checks = [paper_account_check(settings)]
    report = GateReport(
        "gate4", {"name": strategy.name, **strategy.params()}, False, checks, {}, asdict(criteria)
    )

    snapshots = ledger.equity_history(session, settings.account_label)
    enough = len(snapshots) >= days + 1
    checks.append(
        Check(
            "enough_history",
            enough,
            f"{len(snapshots)} daily equity records; {criteria.weeks} weeks needs {days + 1}.",
        )
    )
    if not enough:
        return report

    window = snapshots[-(days + 1) :]
    start, end = window[0].as_of, window[-1].as_of
    paper_return, paper_drawdown = window_stats([row.equity for row in window])

    history = closes_until(start - timedelta(days=1))
    result = run_backtest(history, strategy, limits, config or BacktestConfig(), settings.universe_list)
    returns, drawdowns = rolling_ranges(result.equity, days)
    if len(returns) < criteria.min_windows:
        checks.append(
            Check(
                "backtest_history",
                False,
                f"The backtest before {start} has {len(returns)} windows of {days} days; "
                f"{criteria.min_windows} are needed. Load more history.",
            )
        )
        return report

    low, high = np.percentile(returns, [criteria.low_percentile, criteria.high_percentile])
    worst = float(np.percentile(drawdowns, criteria.high_percentile))
    band = f"{criteria.low_percentile:g}th to {criteria.high_percentile:g}th percentile"
    checks.append(
        Check(
            "return_in_range",
            bool(low <= paper_return <= high),
            f"Paper return {paper_return:+.1%} from {_days([start])} to {_days([end])}. The backtest's {days}-day returns "
            f"ran {low:+.1%} to {high:+.1%} ({band}).",
        )
    )
    checks.append(
        Check(
            "drawdown_in_range",
            paper_drawdown <= worst,
            f"Paper drawdown {paper_drawdown:.1%}. The backtest's {days}-day drawdowns stayed at or under "
            f"{worst:.1%} in {criteria.high_percentile:g}% of windows.",
        )
    )
    report.passed = all(check.passed for check in checks)
    report.details = {
        "paper": {
            "start": start.isoformat(),
            "end": end.isoformat(),
            "return": paper_return,
            "drawdown": paper_drawdown,
        },
        "backtest_windows": len(returns),
        "return_range": [float(low), float(high)],
        "drawdown_limit": worst,
    }
    return report


# ---------------------------------------------------------------- Gate 5


@dataclass(frozen=True)
class Gate5Criteria:
    min_days: int = 63  # shared trading days, about three months
    max_return_gap_pct: float = 2.0  # live and paper total returns at most this many points apart
    max_extra_drawdown_pct: float = 2.0  # live drawdown at most this many points deeper than paper's
    min_correlation: float = 0.9  # daily returns of the two accounts move together


def evaluate_gate5(
    settings: Settings, paper_url: str, paper_label: str = "A", criteria: Gate5Criteria | None = None
) -> GateReport:
    """Compare the live ledger (this settings' database) with a paper ledger over shared days."""
    criteria = criteria or Gate5Criteria()
    checks = [
        Check(
            "live_account",
            settings.is_live,
            "Run this with the live account's settings." if not settings.is_live else "Live account settings",
        )
    ]
    report = GateReport("gate5", {"name": settings.strategy}, False, checks, {}, asdict(criteria))

    live = load_ledger(settings.database_url, settings.account_label)[0]
    paper = load_ledger(paper_url, paper_label)[0]
    common = live.index.intersection(paper.index)
    checks.append(
        Check(
            "enough_days",
            len(common) >= criteria.min_days,
            f"{len(common)} trading days recorded by both accounts; {criteria.min_days} needed.",
        )
    )
    if len(common) < 3:
        return report

    live, paper = live.loc[common], paper.loc[common]
    live_return, live_drawdown = window_stats(live.to_numpy())
    paper_return, paper_drawdown = window_stats(paper.to_numpy())
    gap = abs(live_return - paper_return) * 100
    checks.append(
        Check(
            "return_gap",
            gap <= criteria.max_return_gap_pct,
            f"Live {live_return:+.1%} vs paper {paper_return:+.1%}: {gap:.1f} points apart "
            f"(limit {criteria.max_return_gap_pct:g}).",
        )
    )
    extra = (live_drawdown - paper_drawdown) * 100
    checks.append(
        Check(
            "drawdown_gap",
            extra <= criteria.max_extra_drawdown_pct,
            f"Live drawdown {live_drawdown:.1%} vs paper {paper_drawdown:.1%} "
            f"(live may be at most {criteria.max_extra_drawdown_pct:g} points deeper).",
        )
    )
    correlation = live.pct_change().corr(paper.pct_change())
    tracking = bool(np.isfinite(correlation) and correlation >= criteria.min_correlation)
    checks.append(
        Check(
            "daily_tracking",
            tracking,
            f"Daily returns correlation {correlation:.2f} (needs {criteria.min_correlation:.2f}).",
        )
    )
    report.passed = all(check.passed for check in checks)
    report.details = {
        "start": str(common[0].date()),
        "end": str(common[-1].date()),
        "live": {"return": live_return, "drawdown": live_drawdown},
        "paper": {"return": paper_return, "drawdown": paper_drawdown},
        "correlation": None if not np.isfinite(correlation) else float(correlation),
    }
    return report
