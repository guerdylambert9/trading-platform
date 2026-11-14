"""The risk engine: every order passes these checks in code before it can reach the broker.

The checks are independent of the planner that sized the order, so a sizing bug still gets
caught here. Each rule has a test in tests/test_risk.py that tries to break it.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta

from trader.models import AccountState, OrderIntent, RiskDecision, Side, Violation
from trader.risk.limits import RiskLimits
from trader.utils import NY

EPS = 1e-6


@dataclass
class RiskContext:
    now: datetime
    universe: set[str]
    kill_switch_engaged: bool = False
    orders_submitted_today: int = 0
    used_client_order_ids: set[str] = field(default_factory=set)
    enforce_time_window: bool = False
    session_open: datetime | None = None
    session_close: datetime | None = None
    pending_new_positions: int = 0  # entries already accepted in this batch
    pending_exit_positions: int = 0  # exits planned ahead of these entries
    extra_buying_power: float = 0.0  # cash the planned exits will free


def check_order(
    intent: OrderIntent, account: AccountState, limits: RiskLimits, ctx: RiskContext
) -> RiskDecision:
    violations: list[Violation] = []

    def add(code: str, message: str) -> None:
        violations.append(Violation(code=code, message=message))

    if intent.source == "ai":
        add("ai_cannot_trade", "AI may rank or veto rules signals, but never creates, sizes or sends orders.")
    if intent.qty <= 0:
        add("invalid_qty", f"Quantity must be at least 1 share (got {intent.qty}).")
    if intent.limit_price <= 0:
        add("invalid_price", f"Limit price must be positive (got {intent.limit_price}).")
    if ctx.kill_switch_engaged:
        add("kill_switch", "The kill switch is engaged: no new orders until you release it.")
    if intent.client_order_id in ctx.used_client_order_ids:
        add("duplicate_order", f"Client order ID {intent.client_order_id} was already sent.")
    if ctx.orders_submitted_today >= limits.max_orders_per_day:
        add(
            "order_cap",
            f"{ctx.orders_submitted_today} orders already went out today; the cap is {limits.max_orders_per_day}.",
        )
    if ctx.enforce_time_window:
        _check_time_window(limits, ctx, add)

    if intent.side == Side.BUY:
        _check_entry(intent, account, limits, ctx, add)
    else:
        held = account.positions.get(intent.symbol)
        held_qty = held.qty if held else 0.0
        if intent.qty > held_qty + EPS:
            add(
                "no_shorting",
                f"Selling {intent.qty} {intent.symbol} exceeds the {held_qty:g} shares held; shorting is off.",
            )

    return RiskDecision(approved=not violations, violations=violations)


def _check_time_window(limits: RiskLimits, ctx: RiskContext, add) -> None:  # noqa: ANN001
    if ctx.session_open is None or ctx.session_close is None:
        add("market_closed", "There is no regular trading session today.")
        return
    earliest = ctx.session_open + timedelta(minutes=limits.no_trade_after_open_min)
    latest = ctx.session_close - timedelta(minutes=limits.no_trade_before_close_min)
    if not (earliest <= ctx.now <= latest):
        add(
            "outside_trading_window",
            f"Orders only go out between {earliest.astimezone(NY):%H:%M} and "
            f"{latest.astimezone(NY):%H:%M} New York time.",
        )


def _check_entry(
    intent: OrderIntent, account: AccountState, limits: RiskLimits, ctx: RiskContext, add
) -> None:  # noqa: ANN001
    symbol = intent.symbol
    if symbol not in ctx.universe:
        add("not_in_universe", f"{symbol} is not on the approved ticker list.")
    if account.drawdown_pct >= limits.max_drawdown_pct:
        add(
            "max_drawdown",
            f"The account is {account.drawdown_pct:.1f}% below its peak; new entries stop at "
            f"{limits.max_drawdown_pct:g}%.",
        )
    if account.day_pnl_pct <= -limits.daily_loss_limit_pct:
        add(
            "daily_loss_limit",
            f"Down {abs(account.day_pnl_pct):.2f}% today; new entries stop at -{limits.daily_loss_limit_pct:g}%.",
        )

    equity = account.equity
    if equity <= 0:
        add("no_equity", "Account equity is zero or negative.")
        return

    existing = account.positions.get(symbol)
    existing_value = existing.market_value if existing and existing.qty > 0 else 0.0
    position_pct = (existing_value + intent.notional) / equity * 100
    if position_pct > limits.max_position_pct + EPS:
        add(
            "position_size",
            f"{symbol} would be {position_pct:.1f}% of equity; the limit is {limits.max_position_pct:g}%.",
        )

    if intent.stop_price is None:
        add("missing_stop", "Every entry needs a protective stop.")
    elif intent.stop_price >= intent.limit_price:
        add("invalid_stop", f"Stop {intent.stop_price} must sit below the limit price {intent.limit_price}.")
    else:
        risk_pct = intent.qty * (intent.limit_price - intent.stop_price) / equity * 100
        if risk_pct > limits.risk_per_trade_pct + 0.01:
            add(
                "risk_per_trade",
                f"Loss at the stop would be {risk_pct:.2f}% of equity; the limit is {limits.risk_per_trade_pct:g}%.",
            )

    is_new_position = not (existing and existing.qty > 0)
    if is_new_position:
        open_after = len(account.held_symbols()) - ctx.pending_exit_positions + ctx.pending_new_positions + 1
        if open_after > limits.max_open_positions:
            add(
                "max_positions",
                f"This would be position {open_after}; the limit is {limits.max_open_positions}.",
            )

    if intent.notional > account.buying_power + ctx.extra_buying_power + EPS:
        add(
            "buying_power",
            f"Order needs ${intent.notional:,.2f}; ${account.buying_power + ctx.extra_buying_power:,.2f} is available.",
        )
