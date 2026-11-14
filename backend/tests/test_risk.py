"""One breaking test per risk rule, plus a randomized check of the guarantees."""

from __future__ import annotations

import random
from datetime import UTC, datetime

import pytest

from tests.helpers import TODAY, at
from trader.models import AccountState, IntentKind, OrderIntent, Position, Side
from trader.risk import RiskContext, RiskLimits, check_order

LIMITS = RiskLimits()
NOW = at(TODAY, 10, 30)


def account(**overrides) -> AccountState:
    values = {
        "equity": 100_000.0,
        "cash": 100_000.0,
        "buying_power": 100_000.0,
        "day_start_equity": 100_000.0,
        "peak_equity": 100_000.0,
        "positions": {},
    }
    values.update(overrides)
    return AccountState(**values)


def buy(symbol="SPY", qty=50, limit=100.0, stop: float | None = 92.5, **overrides) -> OrderIntent:
    values = {
        "symbol": symbol,
        "side": Side.BUY,
        "kind": IntentKind.ENTRY,
        "qty": qty,
        "limit_price": limit,
        "stop_price": stop,
        "client_order_id": f"tpA-20261112-{symbol}-buy",
    }
    values.update(overrides)
    return OrderIntent(**values)


def sell(symbol="SPY", qty=10, limit=100.0) -> OrderIntent:
    return OrderIntent(
        symbol=symbol,
        side=Side.SELL,
        kind=IntentKind.EXIT,
        qty=qty,
        limit_price=limit,
        client_order_id=f"tpA-20261112-{symbol}-sell",
    )


def ctx(**overrides) -> RiskContext:
    values = {"now": NOW, "universe": {"SPY", "QQQ", "GLD"}}
    values.update(overrides)
    return RiskContext(**values)


def codes(intent, acct=None, risk_ctx=None, limits=LIMITS) -> set[str]:
    decision = check_order(intent, acct or account(), limits, risk_ctx or ctx())
    assert decision.approved == (not decision.violations)
    assert all(v.message for v in decision.violations)
    return {v.code for v in decision.violations}


def held(n: int) -> dict[str, Position]:
    return {
        f"S{i}": Position(symbol=f"S{i}", qty=10, avg_entry_price=100, current_price=100) for i in range(n)
    }


def test_a_sized_entry_with_a_stop_passes():
    assert codes(buy()) == set()


def test_ai_can_never_send_orders():
    assert "ai_cannot_trade" in codes(buy(source="ai"))


def test_zero_quantity_is_refused():
    assert "invalid_qty" in codes(buy(qty=0))


def test_kill_switch_blocks_everything():
    assert "kill_switch" in codes(buy(), risk_ctx=ctx(kill_switch_engaged=True))
    positions = {"SPY": Position(symbol="SPY", qty=10, avg_entry_price=100, current_price=100)}
    assert "kill_switch" in codes(sell(), account(positions=positions), ctx(kill_switch_engaged=True))


def test_duplicate_client_order_id_is_refused():
    assert "duplicate_order" in codes(buy(), risk_ctx=ctx(used_client_order_ids={"tpA-20261112-SPY-buy"}))


def test_daily_order_cap():
    assert "order_cap" in codes(buy(), risk_ctx=ctx(orders_submitted_today=LIMITS.max_orders_per_day))


def test_time_window_enforced_at_submission():
    session = {
        "session_open": at(TODAY, 9, 30),
        "session_close": at(TODAY, 16, 0),
        "enforce_time_window": True,
    }
    assert "outside_trading_window" in codes(buy(), risk_ctx=ctx(now=at(TODAY, 9, 40), **session))
    assert "outside_trading_window" in codes(buy(), risk_ctx=ctx(now=at(TODAY, 15, 50), **session))
    assert codes(buy(), risk_ctx=ctx(now=at(TODAY, 9, 45), **session)) == set()
    assert "market_closed" in codes(buy(), risk_ctx=ctx(enforce_time_window=True))


def test_unlisted_tickers_are_refused():
    assert "not_in_universe" in codes(buy(symbol="GME"))


def test_drawdown_limit_blocks_entries_but_not_exits():
    deep = {"peak_equity": 120_000.0}
    assert "max_drawdown" in codes(buy(), account(**deep))
    positions = {"SPY": Position(symbol="SPY", qty=10, avg_entry_price=100, current_price=100)}
    assert codes(sell(), account(positions=positions, **deep)) == set()


def test_daily_loss_limit_blocks_entries():
    assert "daily_loss_limit" in codes(buy(), account(day_start_equity=103_000.0))


def test_position_size_limit():
    assert "position_size" in codes(buy(qty=101, stop=99.0))
    positions = {"SPY": Position(symbol="SPY", qty=60, avg_entry_price=100, current_price=100)}
    assert "position_size" in codes(buy(qty=50), account(positions=positions))


def test_entries_need_a_valid_stop():
    assert "missing_stop" in codes(buy(stop=None))
    assert "invalid_stop" in codes(buy(stop=100.0))


def test_risk_per_trade_limit():
    assert "risk_per_trade" in codes(buy(qty=99, stop=85.0))


def test_max_open_positions_counts_planned_exits_and_entries():
    full = account(positions=held(LIMITS.max_open_positions))
    assert "max_positions" in codes(buy(), full)
    assert codes(buy(), full, ctx(pending_exit_positions=1)) == set()
    assert "max_positions" in codes(buy(), account(positions=held(7)), ctx(pending_new_positions=1))


def test_buying_power_includes_cash_freed_by_planned_exits():
    poor = account(cash=1_000.0, buying_power=1_000.0)
    assert "buying_power" in codes(buy(), poor)
    assert codes(buy(), poor, ctx(extra_buying_power=10_000.0)) == set()


def test_no_shorting():
    assert "no_shorting" in codes(sell(qty=5))
    positions = {"SPY": Position(symbol="SPY", qty=4, avg_entry_price=100, current_price=100)}
    assert "no_shorting" in codes(sell(qty=5), account(positions=positions))


def test_max_entry_fraction_combines_position_and_risk_caps():
    assert RiskLimits().max_entry_fraction() == pytest.approx(0.10)
    assert RiskLimits(risk_per_trade_pct=0.5, stop_loss_pct=10).max_entry_fraction() == pytest.approx(0.05)
    assert RiskLimits(stop_loss_pct=0).max_entry_fraction() == pytest.approx(0.10)


def test_randomized_orders_never_break_the_guarantees():
    rng = random.Random(42)
    for _ in range(2_000):
        equity = rng.uniform(5_000, 500_000)
        limit = round(rng.uniform(5, 800), 2)
        stop = round(limit * rng.uniform(0.5, 1.1), 2)
        intent = buy(qty=rng.randint(0, 400), limit=limit, stop=stop if rng.random() > 0.1 else None)
        acct = account(
            equity=equity,
            cash=equity,
            buying_power=equity,
            day_start_equity=equity * rng.uniform(0.95, 1.05),
            peak_equity=equity * rng.uniform(1.0, 1.2),
        )
        decision = check_order(intent, acct, LIMITS, ctx())
        if decision.approved:
            assert (
                intent.qty >= 1 and intent.stop_price is not None and intent.stop_price < intent.limit_price
            )
            assert intent.notional / equity * 100 <= LIMITS.max_position_pct + 1e-6
            risk = intent.qty * (intent.limit_price - intent.stop_price) / equity * 100
            assert risk <= LIMITS.risk_per_trade_pct + 0.01
            assert acct.drawdown_pct < LIMITS.max_drawdown_pct
            assert acct.day_pnl_pct > -LIMITS.daily_loss_limit_pct


def test_context_now_must_be_comparable():
    session = {
        "session_open": datetime(2026, 11, 12, 14, 30, tzinfo=UTC),
        "session_close": datetime(2026, 11, 12, 21, 0, tzinfo=UTC),
    }
    inside = ctx(now=datetime(2026, 11, 12, 16, 0, tzinfo=UTC), enforce_time_window=True, **session)
    assert codes(buy(), risk_ctx=inside) == set()
    late = ctx(now=datetime(2026, 11, 12, 20, 50, tzinfo=UTC), enforce_time_window=True, **session)
    assert "outside_trading_window" in codes(buy(), risk_ctx=late)
