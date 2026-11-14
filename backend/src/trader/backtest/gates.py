"""Gate 1: does the strategy earn its place on held-out data?

Write the criteria down before you run this, and run it once per idea. Every run is logged to
reports/holdout_log.jsonl; each extra look at the holdout makes a pass less trustworthy.
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from dataclasses import asdict, dataclass, field, replace
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pandas as pd

from trader.backtest.engine import BacktestConfig, run_backtest
from trader.backtest.metrics import performance, trade_stats
from trader.backtest.report import benchmark_equity
from trader.risk.limits import RiskLimits
from trader.strategies.base import Strategy


@dataclass(frozen=True)
class Gate1Criteria:
    min_calmar_vs_benchmark: float = 1.0  # holdout Calmar at least this multiple of the benchmark's
    max_drawdown_pct: float = 25.0  # worst holdout drawdown
    min_round_trips: int = 30  # closed trades over the whole run, so results aren't luck
    robustness_floor: float = 0.5  # each ±20% parameter variant keeps this share of the Calmar
    lag2_floor: float = 0.75  # trading a day later keeps this share of the Calmar


@dataclass
class Check:
    name: str
    passed: bool
    detail: str


@dataclass
class GateReport:
    gate: str
    strategy: dict[str, Any]
    passed: bool
    checks: list[Check]
    holdout: dict[str, Any]
    criteria: dict[str, Any]
    details: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _fmt(value: float | None) -> str:
    return "n/a" if value is None else f"{value:.2f}"


def _holdout_calmar(
    closes: pd.DataFrame,
    strategy: Strategy,
    limits: RiskLimits,
    config: BacktestConfig,
    universe: Sequence[str] | None,
    start: pd.Timestamp,
) -> float | None:
    result = run_backtest(closes, strategy, limits, config, universe)
    return performance(result.equity.loc[start:])["calmar"]


def evaluate_gate1(
    closes: pd.DataFrame,
    strategy: Strategy,
    limits: RiskLimits,
    benchmark: str,
    holdout_start: str | pd.Timestamp,
    config: BacktestConfig | None = None,
    criteria: Gate1Criteria | None = None,
    universe: Sequence[str] | None = None,
) -> GateReport:
    config = config or BacktestConfig()
    criteria = criteria or Gate1Criteria()
    start = pd.Timestamp(holdout_start)
    if start >= closes.index[-1]:
        raise ValueError("The holdout starts after the last date in the data.")

    base = run_backtest(closes, strategy, limits, config, universe)
    holdout_equity = base.equity.loc[start:]
    bench = benchmark_equity(closes, benchmark, holdout_equity.index, float(holdout_equity.iloc[0]))
    strat_perf = performance(holdout_equity)
    bench_perf = performance(bench)
    calmar, bench_calmar = strat_perf["calmar"], bench_perf["calmar"]
    checks: list[Check] = []

    if bench_calmar is not None and bench_calmar > 0:
        beats = calmar is not None and calmar >= bench_calmar * criteria.min_calmar_vs_benchmark
    else:  # the benchmark lost money in the holdout: require a positive result that beats it
        beats = (
            calmar is not None
            and calmar > 0
            and (strat_perf["total_return"] or 0) > (bench_perf["total_return"] or 0)
        )
    checks.append(
        Check(
            "beats_benchmark",
            bool(beats and calmar is not None and calmar > 0),
            f"Holdout Calmar {_fmt(calmar)} vs {benchmark} {_fmt(bench_calmar)} "
            f"(needs > 0 and at least {criteria.min_calmar_vs_benchmark:g}x the benchmark)",
        )
    )

    drawdown = abs(strat_perf["max_drawdown"] or 0.0) * 100
    checks.append(
        Check(
            "max_drawdown",
            drawdown <= criteria.max_drawdown_pct,
            f"Worst holdout drawdown {drawdown:.1f}% (limit {criteria.max_drawdown_pct:g}%)",
        )
    )

    round_trips = trade_stats(base.trades)["round_trips"]
    checks.append(
        Check(
            "enough_trades",
            round_trips >= criteria.min_round_trips,
            f"{round_trips} closed trades over the whole run (needs {criteria.min_round_trips})",
        )
    )

    variant_results = []
    robust = calmar is not None and calmar > 0
    for variant in strategy.variants():
        variant_calmar = _holdout_calmar(closes, variant, limits, config, universe, start)
        ok = (
            variant_calmar is not None
            and variant_calmar > 0
            and calmar is not None
            and (variant_calmar >= calmar * criteria.robustness_floor)
        )
        robust = robust and ok
        variant_results.append(f"{variant!r}: {_fmt(variant_calmar)}")
    checks.append(
        Check(
            "robust_to_parameters",
            bool(robust),
            "Holdout Calmar with parameters moved about 20%: "
            + "; ".join(variant_results)
            + f" (each needs at least {criteria.robustness_floor:g}x of {_fmt(calmar)})",
        )
    )

    lag2_calmar = _holdout_calmar(closes, strategy, limits, replace(config, lag=2), universe, start)
    lag_ok = (
        lag2_calmar is not None
        and lag2_calmar > 0
        and calmar is not None
        and (lag2_calmar >= calmar * criteria.lag2_floor)
    )
    checks.append(
        Check(
            "survives_one_day_delay",
            bool(lag_ok),
            f"Holdout Calmar trading one day later: {_fmt(lag2_calmar)} "
            f"(needs at least {criteria.lag2_floor:g}x of {_fmt(calmar)})",
        )
    )

    return GateReport(
        gate="gate1",
        strategy=strategy.describe(),
        passed=all(check.passed for check in checks),
        checks=checks,
        holdout={
            "start": str(holdout_equity.index[0].date()),
            "end": str(holdout_equity.index[-1].date()),
            "strategy": strat_perf,
            "benchmark": {"symbol": benchmark, **bench_perf},
            "round_trips": round_trips,
        },
        criteria=asdict(criteria),
    )


def log_holdout_use(reports_dir: str | Path, report: GateReport) -> int:
    """Append this run to the holdout log; return how many earlier runs used the same strategy."""
    path = Path(reports_dir) / "holdout_log.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    earlier = 0
    if path.exists():
        for line in path.read_text().splitlines():
            try:
                entry = json.loads(line)
            except json.JSONDecodeError:
                continue
            if entry.get("strategy", {}).get("name") == report.strategy.get("name"):
                earlier += 1
    with path.open("a") as handle:
        handle.write(
            json.dumps(
                {
                    "ts": datetime.now(UTC).isoformat(),
                    "strategy": report.strategy,
                    "holdout_start": report.holdout["start"],
                    "passed": report.passed,
                }
            )
            + "\n"
        )
    return earlier
