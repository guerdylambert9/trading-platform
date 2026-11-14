"""Turn target weights into order intents.

The live pipeline and the backtester both call plan_intents, so a backtest trades exactly the
way the live system would. Every live order is a full entry or a full exit: positions that are
held and still targeted are left alone (no trims or top-ups).
"""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from datetime import date

from trader.models import AccountState, IntentKind, OrderIntent, Side
from trader.risk.limits import RiskLimits
from trader.utils import is_number, round_down_cents, round_up_cents


def client_order_id(prefix: str, as_of: date, symbol: str, side: Side) -> str:
    return f"{prefix}-{as_of:%Y%m%d}-{symbol}-{side}"


def plan_intents(
    targets: Mapping[str, float],
    prices: Mapping[str, float],
    account: AccountState,
    limits: RiskLimits,
    universe: Sequence[str],
    as_of: date,
    cid_prefix: str,
    exclude: set[str] | frozenset[str] = frozenset(),
) -> list[OrderIntent]:
    """Plan exits and entries for one rebalance.

    Exits: a held universe symbol whose target is zero is sold in full. Positions outside the
    universe are never touched (they are yours, not the strategy's).
    Entries: an unheld symbol with a positive target is bought at
    min(target, limits.max_entry_fraction()) of equity, capped by the cash left after exits
    and by max_open_positions. Symbols are visited in universe order, so ties resolve the same
    way in the backtest and live.
    """
    buffer = limits.entry_limit_buffer_pct / 100
    intents: list[OrderIntent] = []

    exit_proceeds = 0.0
    exiting: set[str] = set()
    for symbol in universe:
        position = account.positions.get(symbol)
        if position is None or position.qty < 1 or symbol in exclude:
            continue
        weight = targets.get(symbol, 0.0)
        if is_number(weight) and weight > 0:
            continue
        price = prices.get(symbol, position.current_price)
        if not is_number(price) or price <= 0:
            price = position.current_price
        qty = int(position.qty)
        limit = round_down_cents(price * (1 - buffer))
        intents.append(
            OrderIntent(
                symbol=symbol,
                side=Side.SELL,
                kind=IntentKind.EXIT,
                qty=qty,
                limit_price=limit,
                reason=f"{symbol} target dropped to 0%",
                client_order_id=client_order_id(cid_prefix, as_of, symbol, Side.SELL),
            )
        )
        exit_proceeds += qty * limit
        exiting.add(symbol)

    cash = account.cash + exit_proceeds
    held = account.held_symbols() - exiting
    open_count = len(held)
    max_fraction = limits.max_entry_fraction()

    for symbol in universe:
        weight = targets.get(symbol, 0.0)
        if not (is_number(weight) and weight > 0):
            continue
        if symbol in held or symbol in exiting or symbol in exclude:
            continue
        if open_count >= limits.max_open_positions:
            break
        price = prices.get(symbol)
        if not is_number(price) or price <= 0:
            continue
        limit = round_up_cents(price * (1 + buffer))
        dollars = min(min(weight, max_fraction) * account.equity, cash)
        qty = math.floor(dollars / limit)
        if qty < 1:
            continue
        stop = round_up_cents(limit * (1 - limits.stop_loss_pct / 100)) if limits.stop_loss_pct > 0 else None
        intents.append(
            OrderIntent(
                symbol=symbol,
                side=Side.BUY,
                kind=IntentKind.ENTRY,
                qty=qty,
                limit_price=limit,
                stop_price=stop,
                reason=f"{symbol} target {weight:.1%} of equity",
                client_order_id=client_order_id(cid_prefix, as_of, symbol, Side.BUY),
            )
        )
        cash -= qty * limit
        open_count += 1

    return intents
