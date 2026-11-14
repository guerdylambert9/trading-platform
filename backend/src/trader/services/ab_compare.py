"""Gate 3: compare paper account A (rules only) with paper account B (rules + AI).

B passes only if, over at least twelve weeks of shared history, its return after AI costs
beats A and its worst drawdown is no deeper. Each account runs as its own deployment with its
own ledger (database).
"""

from __future__ import annotations

from typing import Any

import pandas as pd
from sqlalchemy import select
from sqlalchemy.orm import Session

from trader import ledger
from trader.backtest.metrics import performance
from trader.db import AIDecisionRow, ProposalRow, make_engine


def load_ledger(url: str, label: str) -> tuple[pd.Series, pd.Series, int]:
    """Daily equity, cumulative AI cost, and the number of AI vetoes from one account's ledger."""
    engine = make_engine(url)
    with Session(engine) as session:
        equity = pd.Series(
            {pd.Timestamp(row.as_of): row.equity for row in ledger.equity_history(session, label)},
            dtype=float,
        ).sort_index()
        costs: dict[pd.Timestamp, float] = {}
        for row in session.scalars(select(AIDecisionRow).where(AIDecisionRow.account_label == label)):
            day = pd.Timestamp(row.as_of)
            costs[day] = costs.get(day, 0.0) + float(row.cost_usd or 0.0)
        vetoes = sum(
            1
            for row in session.scalars(select(ProposalRow).where(ProposalRow.account_label == label))
            if any(v.get("code") == "ai_veto" for v in (row.violations or []))
        )
    engine.dispose()
    cumulative_cost = pd.Series(costs, dtype=float).sort_index().cumsum()
    return equity, cumulative_cost, vetoes


def compare_ab(
    url_a: str, url_b: str, label_a: str = "A", label_b: str = "B", min_days: int = 60
) -> dict[str, Any]:
    equity_a, _, _ = load_ledger(url_a, label_a)
    equity_b, cost_b, vetoes = load_ledger(url_b, label_b)
    common = equity_a.index.intersection(equity_b.index)
    if len(common) < 2:
        raise ValueError("The two ledgers need at least two equity snapshots on the same dates.")
    equity_a, equity_b = equity_a.loc[common], equity_b.loc[common]

    if len(cost_b):
        cost = cost_b.reindex(cost_b.index.union(common)).ffill().fillna(0.0).loc[common]
    else:
        cost = pd.Series(0.0, index=common)
    window_cost = cost - cost.iloc[0]
    net_b = equity_b - window_cost

    perf_a, perf_b = performance(equity_a), performance(net_b)
    return_a, return_b = perf_a["total_return"] or 0.0, perf_b["total_return"] or 0.0
    drawdown_a, drawdown_b = perf_a["max_drawdown"] or 0.0, perf_b["max_drawdown"] or 0.0
    return {
        "start": str(common[0].date()),
        "end": str(common[-1].date()),
        "days": len(common),
        "rules_only": {"label": label_a, **perf_a},
        "rules_plus_ai": {
            "label": label_b,
            **perf_b,
            "ai_cost_usd": float(window_cost.iloc[-1]),
            "ai_vetoes": vetoes,
        },
        "enough_days": len(common) >= min_days,
        "min_days": min_days,
        "passed": bool(len(common) >= min_days and return_b > return_a and drawdown_b >= drawdown_a),
        "rule": (
            f"B passes if, over at least {min_days} shared trading days, its return after AI costs "
            "beats A and its worst drawdown is no deeper."
        ),
    }
