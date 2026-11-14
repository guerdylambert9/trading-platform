from __future__ import annotations

import math

import pytest

from tests.helpers import TODAY, UNIVERSE
from trader.models import AccountState, Position, Side
from trader.planner import plan_intents
from trader.risk import RiskLimits

LIMITS = RiskLimits()
PRICES = {"SPY": 500.0, "QQQ": 400.0, "IWM": 200.0, "EFA": 80.0, "TLT": 90.0, "GLD": 180.0}


def account(cash=100_000.0, positions=None) -> AccountState:
    positions = positions or {}
    equity = cash + sum(p.market_value for p in positions.values())
    return AccountState(
        equity=equity,
        cash=cash,
        buying_power=cash,
        day_start_equity=equity,
        peak_equity=equity,
        positions=positions,
    )


def position(symbol, qty, price=None) -> Position:
    price = price or PRICES.get(symbol, 100.0)
    return Position(symbol=symbol, qty=qty, avg_entry_price=price, current_price=price)


def plan(targets, acct=None, limits=LIMITS, exclude=frozenset(), prices=PRICES):
    return plan_intents(targets, prices, acct or account(), limits, UNIVERSE, TODAY, "tpA", exclude=exclude)


def test_exits_sell_the_whole_position_when_the_target_drops_to_zero():
    intents = plan({"SPY": 0.0}, account(positions={"SPY": position("SPY", 17)}))
    assert len(intents) == 1
    exit_ = intents[0]
    assert exit_.side == Side.SELL and exit_.qty == 17 and exit_.stop_price is None
    assert exit_.limit_price < PRICES["SPY"]


def test_held_and_still_targeted_positions_are_left_alone():
    assert plan({"SPY": 0.1}, account(positions={"SPY": position("SPY", 5)})) == []


def test_entries_are_capped_by_the_risk_limits():
    (entry,) = plan({"SPY": 0.5})
    assert entry.side == Side.BUY
    assert entry.qty == math.floor(10_000 / entry.limit_price)
    assert entry.stop_price == pytest.approx(entry.limit_price * 0.92, abs=0.011)
    assert entry.stop_price < entry.limit_price


def test_entries_are_capped_by_cash():
    (entry,) = plan({"SPY": 0.1, "EFA": 0.1}, account(cash=2_000.0, positions={"EFA": position("EFA", 1000)}))
    assert entry.symbol == "SPY" and entry.notional <= 2_000.0


def test_exit_proceeds_fund_entries():
    acct = account(cash=0.0, positions={"EFA": position("EFA", 125)})
    intents = plan({"EFA": 0.0, "SPY": 0.1}, acct)
    assert [i.side for i in intents] == [Side.SELL, Side.BUY]
    assert intents[1].notional <= intents[0].notional


def test_max_open_positions():
    limits = RiskLimits(max_open_positions=2)
    intents = plan(dict.fromkeys(UNIVERSE, 0.1), limits=limits)
    assert [i.symbol for i in intents] == UNIVERSE[:2]


def test_excluded_and_unpriced_symbols_are_skipped():
    prices = {k: v for k, v in PRICES.items() if k != "QQQ"}
    intents = plan({"SPY": 0.1, "QQQ": 0.1, "GLD": 0.1}, exclude={"SPY"}, prices=prices)
    assert [i.symbol for i in intents] == ["GLD"]


def test_positions_outside_the_universe_are_never_touched():
    assert plan({}, account(positions={"AAPL": position("AAPL", 10, 200.0)})) == []


def test_client_order_ids_are_deterministic():
    first = plan({"SPY": 0.1})[0].client_order_id
    assert first == plan({"SPY": 0.1})[0].client_order_id == "tpA-20261112-SPY-buy"


def test_nan_targets_are_ignored():
    assert plan({"SPY": float("nan")}) == []
