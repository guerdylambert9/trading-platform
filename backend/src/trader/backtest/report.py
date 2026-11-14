"""Turn a backtest into a report: strategy against its benchmark over one window."""

from __future__ import annotations

from dataclasses import asdict
from typing import Any

import pandas as pd

from trader.backtest.engine import BacktestResult
from trader.backtest.metrics import limit_breaches, performance, trade_stats
from trader.risk.limits import RiskLimits


def benchmark_equity(closes: pd.DataFrame, benchmark: str, index: pd.Index, start_value: float) -> pd.Series:
    if benchmark not in closes.columns:
        raise ValueError(f"Benchmark {benchmark} is not in the price data.")
    series = closes[benchmark].reindex(index).ffill().dropna()
    if series.empty:
        raise ValueError(f"No {benchmark} prices in this window.")
    return series / series.iloc[0] * start_value


def backtest_report(
    result: BacktestResult,
    closes: pd.DataFrame,
    benchmark: str,
    limits: RiskLimits,
    start: str | pd.Timestamp | None = None,
    end: str | pd.Timestamp | None = None,
) -> dict[str, Any]:
    equity = result.equity.loc[start:end]
    if len(equity) < 2:
        raise ValueError("Not enough data in this window for a report.")
    first, last = equity.index[0], equity.index[-1]
    bench = benchmark_equity(closes, benchmark, equity.index, float(equity.iloc[0]))
    trades = result.trades
    in_window = trades[
        ((trades["exit_reason"] == "open") & (trades["entry_date"] <= last))
        | ((trades["exit_date"] >= first) & (trades["exit_date"] <= last))
    ]
    return {
        "window": {"start": str(first.date()), "end": str(last.date()), "days": len(equity)},
        "strategy": result.strategy,
        "config": asdict(result.config),
        "performance": performance(equity),
        "benchmark": {"symbol": benchmark, **performance(bench)},
        "trades": trade_stats(in_window),
        "avg_exposure": float(result.exposure.loc[first:last].mean()),
        "kill_switch_check": limit_breaches(equity, limits.max_drawdown_pct, limits.daily_loss_limit_pct),
    }
