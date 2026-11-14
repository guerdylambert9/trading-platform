"""The live path with the fake broker: nightly pipeline, approvals, submission, kill switch, reconcile."""

from __future__ import annotations

from datetime import timedelta

import pandas as pd
import pytest

from tests.helpers import TODAY, MutableClock, at, make_ctx, trending_frame
from trader import ledger
from trader.data.base import FrameBarSource
from trader.models import AIDecision, IntentKind, OrderIntent, ProposalStatus, Side
from trader.services import killswitch
from trader.services.approvals import InvalidTransitionError, decide_proposal
from trader.services.execution import submit_approved
from trader.services.pipeline import run_nightly
from trader.services.reconcile import reconcile

FRIDAY = TODAY + timedelta(days=1)
SATURDAY = TODAY + timedelta(days=2)


def proposals(ctx, status=None):
    with ctx.session() as session:
        return ledger.list_proposals(session, ctx.label, status=status)


def approve_all(ctx):
    with ctx.session() as session:
        for row in ledger.list_proposals(session, ctx.label, status="pending"):
            decide_proposal(session, row.id, True, by="test")


def entries_filled(ctx):
    """Nightly on Thursday, approve, submit Friday morning."""
    run_nightly(ctx)
    approve_all(ctx)
    ctx.now_fn.set(FRIDAY, 10, 0)
    return submit_approved(ctx)


def test_nightly_proposes_entries_for_uptrends_only():
    ctx = make_ctx()
    result = run_nightly(ctx)
    assert result.as_of == TODAY and result.skipped_reason is None
    rows = proposals(ctx)
    symbols = {r.symbol for r in rows}
    assert {"SPY", "QQQ", "GLD"} <= symbols
    assert not symbols & {"EFA", "TLT"}
    for row in rows:
        assert row.status == ProposalStatus.PENDING and row.kind == IntentKind.ENTRY
        assert row.stop_price is not None and row.stop_price < row.limit_price
    with ctx.session() as session:
        assert len(ledger.latest_signals(session, ctx.label)) == 6


def test_nightly_runs_once_per_day():
    ctx = make_ctx()
    run_nightly(ctx)
    again = run_nightly(ctx)
    assert again.skipped_reason and "Already ran" in again.skipped_reason


def test_nightly_waits_for_todays_bar():
    ctx = make_ctx(clock=MutableClock(at(SATURDAY, 17, 15)))
    result = run_nightly(ctx)
    assert result.skipped_reason and "No bar" in result.skipped_reason
    assert proposals(ctx) == []


def test_auto_approve():
    ctx = make_ctx(auto_approve=True)
    run_nightly(ctx)
    assert {r.status for r in proposals(ctx)} == {ProposalStatus.APPROVED}


def test_only_pending_proposals_can_be_decided():
    ctx = make_ctx()
    run_nightly(ctx)
    row = proposals(ctx)[0]
    with ctx.session() as session:
        decide_proposal(session, row.id, False, by="test")
    with ctx.session() as session, pytest.raises(InvalidTransitionError):
        decide_proposal(session, row.id, True, by="test")


def test_kill_switch_blocks_new_proposals():
    ctx = make_ctx()
    with ctx.session() as session:
        killswitch.engage(ctx, session, "test", by="test")
    run_nightly(ctx)
    rows = proposals(ctx)
    assert rows and all(r.status == ProposalStatus.BLOCKED for r in rows)
    assert all(any(v["code"] == "kill_switch" for v in r.violations) for r in rows)


def test_submission_fills_entries_and_leaves_protective_stops():
    ctx = make_ctx()
    result = entries_filled(ctx)
    assert result.submitted and not result.blocked and not result.errors
    held = {p.symbol for p in ctx.broker.get_positions()}
    stops = {o.symbol for o in ctx.broker.get_open_orders() if o.is_protective_stop}
    assert held and held == stops
    assert {r.status for r in proposals(ctx)} == {ProposalStatus.SUBMITTED}
    with ctx.session() as session:
        assert len(ledger.recent_orders(session, ctx.label)) == len(result.submitted)


def test_submission_respects_the_trading_window():
    ctx = make_ctx()
    run_nightly(ctx)
    approve_all(ctx)
    ctx.now_fn.set(FRIDAY, 9, 35)
    result = submit_approved(ctx)
    assert result.blocked and not result.submitted
    assert all(any(v["code"] == "outside_trading_window" for v in r.violations) for r in proposals(ctx))


def test_submission_skips_when_the_market_is_closed():
    ctx = make_ctx()
    run_nightly(ctx)
    approve_all(ctx)
    ctx.now_fn.set(SATURDAY, 10, 0)
    assert submit_approved(ctx).skipped_reason == "The market is closed."


def test_gap_guard_blocks_entries_after_a_big_jump():
    ctx = make_ctx()
    run_nightly(ctx)
    approve_all(ctx)
    ctx.broker.set_prices({s: p * 1.05 for s, p in ctx.broker.prices.items()})
    ctx.now_fn.set(FRIDAY, 10, 0)
    result = submit_approved(ctx)
    assert result.blocked and not result.submitted
    assert all(any(v["code"] == "gap_too_large" for v in r.violations) for r in proposals(ctx))


def test_dry_run_never_reaches_the_broker():
    ctx = make_ctx(dry_run=True)
    run_nightly(ctx)
    approve_all(ctx)
    ctx.now_fn.set(FRIDAY, 10, 0)
    result = submit_approved(ctx)
    assert result.dry_run and not result.submitted
    assert ctx.broker.orders == {}


def test_exit_cancels_the_stop_then_sells():
    ctx = make_ctx()
    entries_filled(ctx)
    base = trending_frame()
    crash_days = pd.bdate_range(FRIDAY, periods=2)
    crash = pd.DataFrame([base.iloc[-1].to_dict()] * 2, index=crash_days)
    crash["SPY"] = 300.0
    ctx.bars = FrameBarSource(pd.concat([base, crash]))
    ctx.now_fn.set(FRIDAY, 17, 15)
    run_nightly(ctx)
    exits = [r for r in proposals(ctx, "pending") if r.kind == IntentKind.EXIT]
    assert [r.symbol for r in exits] == ["SPY"]
    approve_all(ctx)
    monday = crash_days[-1].date()
    ctx.now_fn.set(monday, 10, 0)
    result = submit_approved(ctx)
    assert result.submitted and not result.blocked
    assert "SPY" not in {p.symbol for p in ctx.broker.get_positions()}
    assert "SPY" not in {o.symbol for o in ctx.broker.get_open_orders()}
    assert "QQQ" in {o.symbol for o in ctx.broker.get_open_orders() if o.is_protective_stop}


def test_kill_switch_cancels_entries_but_keeps_stops():
    ctx = make_ctx()
    entries_filled(ctx)
    pending_entry = ctx.broker.submit_limit_order(
        OrderIntent(
            symbol="IWM",
            side=Side.BUY,
            kind=IntentKind.ENTRY,
            qty=1,
            limit_price=1.0,
            stop_price=0.9,
            client_order_id="tpA-manual-IWM-buy",
        )
    )
    assert pending_entry.is_open
    with ctx.session() as session:
        canceled = killswitch.engage(ctx, session, "test", by="test")
    assert canceled == 1
    assert ctx.broker.orders[pending_entry.id].status == "canceled"
    assert all(o.is_protective_stop for o in ctx.broker.get_open_orders())
    with ctx.session() as session:
        killswitch.release(ctx, session, by="test")
        assert not killswitch.is_engaged(session)


def test_reconcile_is_clean_after_a_normal_day():
    ctx = make_ctx()
    entries_filled(ctx)
    ctx.now_fn.set(FRIDAY, 16, 30)
    result = reconcile(ctx)
    assert result.ok, result.mismatches
    assert {r.status for r in proposals(ctx)} == {ProposalStatus.FILLED}
    with ctx.session() as session:
        assert len(ledger.equity_history(session, ctx.label)) == 1


def test_reconcile_flags_unprotected_positions_and_unknown_orders():
    ctx = make_ctx()
    entries_filled(ctx)
    stop = next(o for o in ctx.broker.get_open_orders() if o.symbol == "SPY")
    ctx.broker.cancel_order(stop.id)
    ctx.broker.submit_limit_order(
        OrderIntent(
            symbol="GLD",
            side=Side.BUY,
            kind=IntentKind.ENTRY,
            qty=1,
            limit_price=1.0,
            client_order_id="tpA-rogue-GLD-buy",
        )
    )
    ctx.now_fn.set(FRIDAY, 11, 0)
    result = reconcile(ctx)
    kinds = {m["type"] for m in result.mismatches}
    assert {"unprotected_position", "unknown_order"} <= kinds
    assert not result.ok


def test_reconcile_cancels_unfilled_entries_after_the_close():
    ctx = make_ctx()
    ctx.broker.set_prices({"SPY": 500.0})
    order = ctx.broker.submit_limit_order(
        OrderIntent(
            symbol="SPY",
            side=Side.BUY,
            kind=IntentKind.ENTRY,
            qty=1,
            limit_price=1.0,
            stop_price=0.9,
            client_order_id="tpA-20261112-SPY-buy",
        )
    )
    ctx.now_fn.set(TODAY, 16, 30)
    result = reconcile(ctx)
    assert result.canceled_stale_entries == 1
    assert ctx.broker.orders[order.id].status == "canceled"


def test_reconcile_engages_the_kill_switch_at_the_drawdown_limit():
    ctx = make_ctx()
    with ctx.session() as session:
        ledger.set_state(session, "peak_equity", 130_000.0)
    result = reconcile(ctx)
    assert result.kill_switch_engaged
    with ctx.session() as session:
        assert killswitch.is_engaged(session)


class StubResearcher:
    name = "stub"

    def __init__(self, ratings):
        self.ratings = ratings
        self.calls = 0

    def review(self, symbol, as_of):
        self.calls += 1
        return AIDecision(
            symbol=symbol, as_of=as_of, rating=self.ratings.get(symbol, "hold"), model="stub", cost_usd=0.25
        )


def test_ai_veto_blocks_only_the_vetoed_entry():
    ctx = make_ctx(researcher=StubResearcher({"SPY": "sell"}), ai_mode="veto", ai_max_calls_per_day=10)
    run_nightly(ctx)
    rows = {r.symbol: r for r in proposals(ctx)}
    assert rows["SPY"].status == ProposalStatus.BLOCKED
    assert any(v["code"] == "ai_veto" for v in rows["SPY"].violations)
    assert rows["QQQ"].status == ProposalStatus.PENDING and rows["QQQ"].ai_rating == "hold"
    with ctx.session() as session:
        assert len(ledger.recent_ai_decisions(session, ctx.label)) == len(rows)


def test_ai_log_only_records_but_never_blocks():
    ctx = make_ctx(researcher=StubResearcher({"SPY": "sell"}), ai_mode="log_only", ai_max_calls_per_day=10)
    run_nightly(ctx)
    assert all(r.status == ProposalStatus.PENDING for r in proposals(ctx))


def test_ai_daily_call_limit():
    stub = StubResearcher({})
    ctx = make_ctx(researcher=stub, ai_mode="veto", ai_max_calls_per_day=1)
    run_nightly(ctx)
    assert stub.calls == 1
    with ctx.session() as session:
        assert ledger.ai_calls_on(session, TODAY, ctx.label) == 1
