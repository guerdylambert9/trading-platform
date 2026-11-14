"""After-close reconciliation: does what the ledger says match what the broker holds?

Checks: every submitted order exists at the broker; no unknown orders carry our prefix;
every position has a protective stop; no positions outside the universe. It also cancels
entries that didn't fill, records the day's equity, and engages the kill switch when the
drawdown limit is hit.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import timedelta
from typing import TYPE_CHECKING, Any

from trader import ledger
from trader.models import ProposalStatus, Side
from trader.services import killswitch
from trader.services.account import PEAK_KEY

if TYPE_CHECKING:
    from trader.services.context import AppContext

log = logging.getLogger(__name__)

DONE_AT_BROKER = {"canceled", "expired", "rejected", "done_for_day", "stopped", "suspended"}


@dataclass
class ReconcileResult:
    ok: bool
    mismatches: list[dict[str, Any]] = field(default_factory=list)
    canceled_stale_entries: int = 0
    kill_switch_engaged: bool = False
    equity: float | None = None


def reconcile(ctx: AppContext) -> ReconcileResult:
    settings = ctx.settings
    prefix = settings.client_order_prefix + "-"
    now = ctx.now()
    mismatches: list[dict[str, Any]] = []
    canceled = 0
    engaged_now = False

    with ctx.session() as session:
        broker_orders = ctx.broker.get_orders_since(now - timedelta(days=10))
        by_client_id = {o.client_order_id: o for o in broker_orders}

        submitted = ledger.proposals_with_status(session, ctx.label, {ProposalStatus.SUBMITTED})
        for row in submitted:
            order = by_client_id.get(row.client_order_id) or ctx.broker.get_order_by_client_id(
                row.client_order_id
            )
            if order is None:
                mismatches.append(
                    {
                        "type": "missing_at_broker",
                        "proposal_id": row.id,
                        "message": f"Proposal #{row.id} ({row.client_order_id}) was submitted but the broker has no such order.",
                    }
                )
                continue
            ledger.upsert_order(session, order, ctx.label, proposal_id=row.id)
            if order.status == "filled":
                row.status = ProposalStatus.FILLED
            elif order.status in DONE_AT_BROKER:
                row.status = ProposalStatus.CANCELED
                row.error = f"Broker status: {order.status}"

        known = ledger.used_client_order_ids(session) | {row.client_order_id for row in submitted}
        for order in broker_orders:
            if (
                order.parent_id is None
                and order.client_order_id.startswith(prefix)
                and order.client_order_id not in known
            ):
                mismatches.append(
                    {
                        "type": "unknown_order",
                        "client_order_id": order.client_order_id,
                        "message": f"Broker order {order.client_order_id} ({order.side} {order.qty:g} {order.symbol}) is not in the ledger.",
                    }
                )

        open_orders = ctx.broker.get_open_orders()
        protected = {o.symbol for o in open_orders if o.is_protective_stop}
        universe = set(settings.universe_list)
        for position in ctx.broker.get_positions():
            if position.qty <= 0:
                continue
            if position.symbol not in protected:
                mismatches.append(
                    {
                        "type": "unprotected_position",
                        "symbol": position.symbol,
                        "message": f"{position.symbol}: {position.qty:g} shares with no protective stop at the broker.",
                    }
                )
            if position.symbol not in universe:
                mismatches.append(
                    {
                        "type": "unmanaged_position",
                        "symbol": position.symbol,
                        "message": f"{position.symbol} is held but is not in the strategy's universe.",
                    }
                )

        if not ctx.broker.clock().is_open:
            for order in open_orders:
                if order.side == Side.BUY and order.client_order_id.startswith(prefix):
                    ctx.broker.cancel_order(order.id)
                    canceled += 1
                    ledger.audit(session, "stale_entry_canceled", client_order_id=order.client_order_id)

        info = ctx.broker.get_account()
        peak = max(float(ledger.get_state(session, PEAK_KEY, info.equity) or info.equity), info.equity)
        ledger.set_state(session, PEAK_KEY, peak)
        try:
            benchmark_price: float | None = ctx.broker.latest_price(settings.benchmark_symbol)
        except Exception:
            benchmark_price = None
        ledger.record_equity(session, ctx.today(), info.equity, info.cash, benchmark_price, ctx.label)

        drawdown = (peak - info.equity) / peak * 100 if peak > 0 else 0.0
        if drawdown >= settings.max_drawdown_pct and not killswitch.is_engaged(session):
            killswitch.engage(
                ctx,
                session,
                reason=f"Drawdown of {drawdown:.1f}% reached the {settings.max_drawdown_pct:g}% limit",
                by="reconcile",
            )
            engaged_now = True

        ok = not mismatches
        ledger.record_reconciliation(session, ok, mismatches, ctx.label, at=now)
        ledger.set_state(
            session, "last_reconcile_run", {"at": now.isoformat(), "ok": ok, "mismatches": len(mismatches)}
        )

    if mismatches:
        ctx.notify(
            f"[{settings.mode_label} {ctx.label}] Reconciliation found {len(mismatches)} problem(s):\n"
            + "\n".join(m["message"] for m in mismatches[:10])
        )
    return ReconcileResult(
        ok=not mismatches,
        mismatches=mismatches,
        canceled_stale_entries=canceled,
        kill_switch_engaged=engaged_now,
        equity=info.equity,
    )
