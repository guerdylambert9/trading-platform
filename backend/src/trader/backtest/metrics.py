"""Performance and trade statistics. Missing values are None so reports serialize to JSON."""

from __future__ import annotations

import math
from typing import Any

import numpy as np
import pandas as pd

TRADING_DAYS = 252
PERFORMANCE_KEYS = ("total_return", "cagr", "volatility", "sharpe", "sortino", "max_drawdown", "calmar")


def _clean(value: Any) -> float | None:
    if value is None:
        return None
    number = float(value)
    return number if math.isfinite(number) else None


def performance(equity: pd.Series) -> dict[str, Any]:
    series = equity.dropna()
    if len(series) < 2 or series.iloc[0] <= 0:
        return dict.fromkeys(PERFORMANCE_KEYS) | {"days": max(len(series) - 1, 0)}

    returns = series.pct_change().dropna()
    years = len(returns) / TRADING_DAYS
    growth = float(series.iloc[-1] / series.iloc[0])
    cagr = growth ** (1 / years) - 1 if years > 0 and growth > 0 else None
    std = float(returns.std(ddof=1)) if len(returns) > 1 else float("nan")
    volatility = std * math.sqrt(TRADING_DAYS)
    sharpe = float(returns.mean()) / std * math.sqrt(TRADING_DAYS) if std > 0 else None
    downside = float(np.sqrt((returns.clip(upper=0) ** 2).mean())) * math.sqrt(TRADING_DAYS)
    sortino = float(returns.mean()) * TRADING_DAYS / downside if downside > 0 else None
    max_drawdown = float((series / series.cummax() - 1).min())
    calmar = cagr / abs(max_drawdown) if cagr is not None and max_drawdown < 0 else None
    return {
        "total_return": _clean(growth - 1),
        "cagr": _clean(cagr),
        "volatility": _clean(volatility),
        "sharpe": _clean(sharpe),
        "sortino": _clean(sortino),
        "max_drawdown": _clean(max_drawdown),
        "calmar": _clean(calmar),
        "days": len(returns),
    }


def trade_stats(trades: pd.DataFrame) -> dict[str, Any]:
    closed = trades[trades["exit_reason"] != "open"]
    wins = closed[closed["return_pct"] > 0]
    losses = closed[closed["return_pct"] <= 0]
    return {
        "round_trips": len(closed),
        "open_positions": int((trades["exit_reason"] == "open").sum()),
        "win_rate": _clean(len(wins) / len(closed)) if len(closed) else None,
        "avg_win_pct": _clean(wins["return_pct"].mean()) if len(wins) else None,
        "avg_loss_pct": _clean(losses["return_pct"].mean()) if len(losses) else None,
        "stopped_out": int((closed["exit_reason"] == "stop").sum()),
    }


def limit_breaches(equity: pd.Series, max_drawdown_pct: float, daily_loss_pct: float) -> dict[str, int]:
    """How often the live kill switch and daily loss limit would have fired.

    The backtest keeps trading through them, as if you reviewed and released the kill switch
    each time; this count shows how often that review would have happened.
    """
    series = equity.dropna()
    if len(series) < 2:
        return {"drawdown_limit_breaches": 0, "daily_loss_limit_days": 0}
    drawdown = (series.cummax() - series) / series.cummax() * 100
    in_breach = drawdown >= max_drawdown_pct
    episodes = int((in_breach & ~in_breach.shift(1, fill_value=False)).sum())
    daily = series.pct_change().dropna() * 100
    return {
        "drawdown_limit_breaches": episodes,
        "daily_loss_limit_days": int((daily <= -daily_loss_pct).sum()),
    }
