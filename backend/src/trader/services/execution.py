"""Morning submission: send approved proposals to the broker, after a fresh risk check.

Each order is re-priced from the latest trade, re-sized to the current limits, and checked
again with the time window enforced. Exits go first and cancel their protective stop
before selling, since the broker holds those shares for the stop.
"""

from __future__ import annotations

import logging
import math
import time
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from trader import ledger
from trader.db import ProposalRow
from trader.models import AccountState, IntentKind, OrderIntent, ProposalStatus, Side, Violation
from trader.risk.engine import RiskContext, check_order
from trader.services import killswitch
from trader.services.account import load_account_state
from trader.utils import round_down_cents, round_up_cents

if TYPE_CHECKING:
    from trader.broker import Broker
    from trader.services.context import AppContext

log = logging.getLogger(__name__)


@dataclass
class SubmitResult:
    submitted: list[int] = field(default_factory=list)
    blocked: list[int] = field(default_factory=list)
    dry_run: list[int] = field(default_factory=list)
    errors: list[int] = field(default_factory=list)
    expired: list[int] = field(default_factory=list)
    skipped_reason: str | None = None


def refresh_intent(
    ctx: AppContext, row: ProposalRow, account: AccountState
) -> tuple[OrderIntent | None, Violation | None]:
    """Re-price and re-size a proposal at the current market price."""
    settings = ctx.settings
    limits = ctx.limits
    buffer = limits.entry_limit_buffer_pct / 100
    price = ctx.broker.latest_price(row.symbol)

    if row.side == Side.SELL:
        position = account.positions.get(row.symbol)
        if position is None or position.qty < 1:
            return None, Violation(
                code="no_position",
                message=f"No {row.symbol} shares left to sell (a stop may have closed it).",
            )
        return (
            OrderIntent(
                symbol=row.symbol,
                side=Side.SELL,
                kind=IntentKind.EXIT,
                qty=int(position.qty),
                limit_price=round_down_cents(price * (1 - buffer)),
                source=row.source,
                reason=row.reason,
                client_order_id=row.client_order_id,
            ),
            None,
        )

    if price > row.est_price * (1 + settings.max_gap_pct / 100):
        return None, Violation(
            code="gap_too_large",
            message=f"{row.symbol} is at {price:.2f}, more than {settings.max_gap_pct:g}% above the "
            f"{row.est_price:.2f} close it was sized on.",
        )
    limit = round_up_cents(price * (1 + buffer))
    stop = round_up_cents(limit * (1 - limits.stop_loss_pct / 100)) if limits.stop_loss_pct > 0 else None
    cap_by_limits = math.floor(limits.max_entry_fraction() * account.equity / limit)
    cap_by_cash = math.floor(account.buying_power / limit)
    qty = min(row.qty, cap_by_limits, cap_by_cash)
    if qty < 1:
        return None, Violation(
            code="insufficient_cash", message=f"Not enough buying power for one {row.symbol} share."
        )
    return (
        OrderIntent(
            symbol=row.symbol,
            side=Side.BUY,
            kind=IntentKind.ENTRY,
            qty=qty,
            limit_price=limit,
            stop_price=stop,
            source=row.source,
            reason=row.reason,
            client_order_id=row.client_order_id,
        ),
        None,
    )


def cancel_symbol_orders(broker: Broker, symbol: str, wait_seconds: float = 5.0) -> int:
    """Cancel open orders for one symbol (its protective stop) and wait for the broker to release the shares."""
    orders = broker.get_open_orders(symbol)
    for order in orders:
        broker.cancel_order(order.id)
    deadline = time.monotonic() + wait_seconds
    while orders and broker.get_open_orders(symbol) and time.monotonic() < deadline:
        time.sleep(0.25)
    return len(orders)


def submit_approved(ctx: AppContext) -> SubmitResult:
    settings = ctx.settings
    result = SubmitResult()
    with ctx.session() as session:
        if killswitch.is_engaged(session):
            result.skipped_reason = "The kill switch is engaged."
            return result
        clock = ctx.broker.clock()
        if not clock.is_open:
            result.skipped_reason = "The market is closed."
            return result

        today = ctx.today()
        result.expired = ledger.expire_stale(session, ctx.label, today)
        proposals = ledger.approved_unsubmitted(session, ctx.label)
        if not proposals:
            result.skipped_reason = "Nothing approved to submit."
            return result

        used_ids = ledger.used_client_order_ids(session)
        sent_today = ledger.orders_submitted_on(session, today, ctx.tz, ctx.label)
        account = load_account_state(ctx, session)
        new_entries: set[str] = set()

        for row in proposals:
            try:
                intent, problem = refresh_intent(ctx, row, account)
                violations = [problem] if problem else []
                if intent is not None:
                    risk_ctx = RiskContext(
                        now=ctx.now(),
                        universe=set(settings.universe_list),
                        kill_switch_engaged=False,
                        orders_submitted_today=sent_today,
                        used_client_order_ids=used_ids,
                        enforce_time_window=True,
                        session_open=clock.session_open,
                        session_close=clock.session_close,
                        pending_new_positions=len(new_entries - account.held_symbols()),
                    )
                    violations = list(check_order(intent, account, ctx.limits, risk_ctx).violations)
                if violations or intent is None:
                    row.status = ProposalStatus.BLOCKED
                    row.violations = [v.model_dump() for v in violations]
                    result.blocked.append(row.id)
                    continue
                if settings.dry_run:
                    row.status = ProposalStatus.DRY_RUN
                    row.limit_price, row.stop_price, row.qty = (
                        intent.limit_price,
                        intent.stop_price,
                        intent.qty,
                    )
                    ledger.audit(session, "dry_run_order", proposal_id=row.id, intent=intent)
                    result.dry_run.append(row.id)
                    continue
                if intent.side == Side.SELL:
                    cancel_symbol_orders(ctx.broker, intent.symbol)
                order = ctx.broker.submit_limit_order(intent)
                row.status = ProposalStatus.SUBMITTED
                row.submitted_at = ctx.now()
                row.broker_order_id = order.id
                row.limit_price, row.stop_price, row.qty = intent.limit_price, intent.stop_price, intent.qty
                order_row = ledger.upsert_order(session, order, ctx.label, proposal_id=row.id)
                if order_row.stop_price is None:
                    order_row.stop_price = intent.stop_price  # the protective leg of an OTO entry
                ledger.audit(session, "order_submitted", proposal_id=row.id, order_id=order.id, intent=intent)
                result.submitted.append(row.id)
                sent_today += 1
                used_ids.add(intent.client_order_id)
                if intent.side == Side.BUY:
                    new_entries.add(intent.symbol)
                account = load_account_state(ctx, session)
            except Exception as exc:
                log.exception("Submitting proposal #%s failed", row.id)
                row.status = ProposalStatus.ERROR
                row.error = str(exc)[:500]
                ledger.audit(session, "order_error", proposal_id=row.id, error=str(exc))
                result.errors.append(row.id)

        ledger.set_state(
            session,
            "last_submit_run",
            {"at": ctx.now().isoformat(), "submitted": len(result.submitted), "blocked": len(result.blocked)},
        )
    if result.submitted or result.blocked or result.errors or result.dry_run:
        ctx.notify(
            f"[{settings.mode_label} {ctx.label}] Submitted {len(result.submitted)}, blocked {len(result.blocked)}, "
            f"dry run {len(result.dry_run)}, errors {len(result.errors)}."
        )
    return result
