"""Daily backtester that trades through the same planner the live system uses.

Each day: mark positions to the close, fire stops whose level the close has reached, then ask
plan_intents for exits and entries and fill them at that close plus costs. With lag=1 a signal
trades at the close it was computed on (slightly optimistic); lag=2 trades one day later
(pessimistic). Live fills, at the next morning's price, land in between, so a strategy worth
trading should survive both.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

import numpy as np
import pandas as pd

from trader.models import AccountState, Position, Side
from trader.planner import plan_intents
from trader.risk.limits import RiskLimits
from trader.strategies.base import Strategy

TRADE_COLUMNS = [
    "symbol",
    "entry_date",
    "entry_price",
    "qty",
    "exit_date",
    "exit_price",
    "return_pct",
    "exit_reason",
]
FILL_COLUMNS = ["date", "symbol", "side", "qty", "price", "notional"]


@dataclass(frozen=True)
class BacktestConfig:
    initial_capital: float = 100_000.0
    cost_bps: float = 5.0  # per side: spread and slippage (Alpaca charges no commission)
    lag: int = 1
    use_stops: bool = True

    def __post_init__(self) -> None:
        if self.lag < 1:
            raise ValueError("lag must be at least 1")
        if self.initial_capital <= 0:
            raise ValueError("initial_capital must be positive")
        if self.cost_bps < 0:
            raise ValueError("cost_bps cannot be negative")


@dataclass
class BacktestResult:
    equity: pd.Series
    trades: pd.DataFrame
    fills: pd.DataFrame
    open_positions: pd.Series
    exposure: pd.Series
    config: BacktestConfig
    strategy: dict[str, Any]


def run_backtest(
    closes: pd.DataFrame,
    strategy: Strategy,
    limits: RiskLimits,
    config: BacktestConfig | None = None,
    universe: Sequence[str] | None = None,
) -> BacktestResult:
    config = config or BacktestConfig()
    symbols = [s for s in (universe or list(closes.columns)) if s in closes.columns]
    if not symbols:
        raise ValueError("None of the universe symbols are in the price data.")
    if len(closes) < 2:
        raise ValueError("Need at least two days of prices.")

    prices = closes[symbols].astype(float)
    weights = strategy.target_weights(prices).reindex(columns=symbols).fillna(0.0)
    targets = weights.shift(config.lag - 1).fillna(0.0)
    cost = config.cost_bps / 10_000

    cash = config.initial_capital
    shares: dict[str, int] = {}
    stops: dict[str, float | None] = {}
    entries: dict[str, tuple[pd.Timestamp, float]] = {}
    last_price: dict[str, float] = {}
    trades: list[dict[str, Any]] = []
    fills: list[dict[str, Any]] = []
    equity_values: list[float] = []
    open_counts: list[int] = []
    exposure_values: list[float] = []
    peak = previous_equity = config.initial_capital

    price_matrix = prices.to_numpy()
    target_matrix = targets.to_numpy()

    def close_position(symbol: str, when: pd.Timestamp, price: float, reason: str) -> None:
        nonlocal cash
        qty = shares.pop(symbol)
        net_price = price * (1 - cost)
        cash += qty * net_price
        entry_date, entry_price = entries.pop(symbol)
        stops.pop(symbol, None)
        trades.append(
            {
                "symbol": symbol,
                "entry_date": entry_date,
                "entry_price": entry_price,
                "qty": qty,
                "exit_date": when,
                "exit_price": net_price,
                "return_pct": (net_price / entry_price - 1) * 100,
                "exit_reason": reason,
            }
        )
        fills.append(
            {
                "date": when,
                "symbol": symbol,
                "side": "sell",
                "qty": qty,
                "price": price,
                "notional": qty * price,
            }
        )

    for i, when in enumerate(prices.index):
        today: dict[str, float] = {}
        for j, symbol in enumerate(symbols):
            value = price_matrix[i, j]
            if np.isfinite(value) and value > 0:
                today[symbol] = float(value)
                last_price[symbol] = float(value)

        stopped: set[str] = set()
        if config.use_stops:
            for symbol in list(shares):
                stop = stops.get(symbol)
                price = today.get(symbol)
                if stop is not None and price is not None and price <= stop:
                    close_position(symbol, when, price, "stop")
                    stopped.add(symbol)

        holdings = sum(qty * last_price[s] for s, qty in shares.items())
        equity = cash + holdings
        account = AccountState(
            equity=equity,
            cash=cash,
            buying_power=cash,
            day_start_equity=previous_equity,
            peak_equity=max(peak, equity),
            positions={
                s: Position(symbol=s, qty=q, avg_entry_price=entries[s][1], current_price=last_price[s])
                for s, q in shares.items()
            },
        )
        day_targets = {symbol: float(target_matrix[i, j]) for j, symbol in enumerate(symbols)}
        missing = {s for s in symbols if s not in today}
        intents = plan_intents(
            day_targets, today, account, limits, symbols, when.date(), "bt", exclude=stopped | missing
        )
        for intent in intents:
            price = today[intent.symbol]
            if intent.side == Side.SELL:
                close_position(intent.symbol, when, price, "signal")
                continue
            fill_price = price * (1 + cost)
            qty = min(intent.qty, int(cash // fill_price))
            if qty < 1:
                continue
            cash -= qty * fill_price
            shares[intent.symbol] = qty
            stops[intent.symbol] = intent.stop_price
            entries[intent.symbol] = (when, fill_price)
            fills.append(
                {
                    "date": when,
                    "symbol": intent.symbol,
                    "side": "buy",
                    "qty": qty,
                    "price": price,
                    "notional": qty * price,
                }
            )

        holdings = sum(qty * last_price[s] for s, qty in shares.items())
        equity = cash + holdings
        peak = max(peak, equity)
        previous_equity = equity
        equity_values.append(equity)
        open_counts.append(len(shares))
        exposure_values.append(holdings / equity if equity > 0 else 0.0)

    for symbol, qty in shares.items():
        entry_date, entry_price = entries[symbol]
        price = last_price[symbol]
        trades.append(
            {
                "symbol": symbol,
                "entry_date": entry_date,
                "entry_price": entry_price,
                "qty": qty,
                "exit_date": pd.NaT,
                "exit_price": price,
                "return_pct": (price / entry_price - 1) * 100,
                "exit_reason": "open",
            }
        )

    index = prices.index
    return BacktestResult(
        equity=pd.Series(equity_values, index=index, name="equity"),
        trades=pd.DataFrame(trades, columns=TRADE_COLUMNS),
        fills=pd.DataFrame(fills, columns=FILL_COLUMNS),
        open_positions=pd.Series(open_counts, index=index, name="open_positions"),
        exposure=pd.Series(exposure_values, index=index, name="exposure"),
        config=config,
        strategy=strategy.describe(),
    )
