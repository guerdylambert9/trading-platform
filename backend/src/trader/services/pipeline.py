"""The nightly pipeline, run after the close.

prices -> strategy targets -> signal ledger -> planned entries/exits -> optional AI review
-> risk checks -> proposals waiting for your approval (or blocked, with the reasons).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import TYPE_CHECKING

import pandas as pd

from trader import ledger
from trader.config import AIMode
from trader.models import AIDecision, IntentKind, ProposalStatus, Side, Violation
from trader.planner import plan_intents
from trader.risk.engine import RiskContext, check_order
from trader.services import killswitch
from trader.services.account import load_account_state
from trader.services.notifications import notify_proposals
from trader.utils import is_number

if TYPE_CHECKING:
    from sqlalchemy.orm import Session

    from trader.services.context import AppContext

log = logging.getLogger(__name__)


@dataclass
class PipelineResult:
    as_of: date | None
    skipped_reason: str | None = None
    targets: dict[str, float] = field(default_factory=dict)
    proposal_ids: list[int] = field(default_factory=list)
    pending: int = 0
    approved: int = 0
    blocked: int = 0


def review_with_budget(ctx: AppContext, session: Session, symbol: str, as_of: date) -> AIDecision:
    """Ask the AI researcher about one symbol, within the daily call limit, and log the answer."""
    settings = ctx.settings
    if ledger.ai_calls_on(session, as_of, ctx.label) >= settings.ai_max_calls_per_day:
        return AIDecision(symbol=symbol, as_of=as_of, summary="Daily AI call limit reached; no review.")
    try:
        decision = ctx.researcher.review(symbol, as_of)
    except Exception as exc:
        log.exception("AI review failed for %s", symbol)
        decision = AIDecision(symbol=symbol, as_of=as_of, summary=f"AI review failed: {exc}")
    if decision.cost_usd is None and settings.ai_cost_per_call_usd:
        decision = decision.model_copy(update={"cost_usd": settings.ai_cost_per_call_usd})
    ledger.record_ai_decision(session, decision, ctx.label)
    return decision


def run_nightly(ctx: AppContext, as_of: date | None = None, force: bool = False) -> PipelineResult:
    settings = ctx.settings
    universe = settings.universe_list
    end = as_of or ctx.today()
    start = end - timedelta(days=ctx.strategy.history_days())
    symbols = list(dict.fromkeys([*universe, settings.benchmark_symbol]))
    closes = ctx.bars.get_closes(symbols, start, end)
    if closes.empty:
        return PipelineResult(as_of=None, skipped_reason="No price data returned.")

    last_date = closes.index[-1].date()
    if as_of is None and last_date != end and not force:
        return PipelineResult(
            as_of=last_date, skipped_reason=f"No bar for {end} yet (market holiday, or data not ready)."
        )

    universe_closes = closes[[s for s in universe if s in closes.columns]]
    weights = ctx.strategy.target_weights(universe_closes)
    last_row = universe_closes.iloc[-1]
    targets = {s: float(weights.iloc[-1][s]) for s in universe_closes.columns}
    prices = {
        s: float(last_row[s])
        for s in universe_closes.columns
        if is_number(last_row[s]) and pd.notna(last_row[s])
    }
    ctx.sync_fake_prices(prices)

    result = PipelineResult(as_of=last_date, targets=targets)
    rows = []
    with ctx.session() as session:
        if not force and ledger.signals_exist(session, last_date, ctx.strategy.name, ctx.label):
            result.skipped_reason = f"Already ran for {last_date}."
            return result
        if not ledger.signals_exist(session, last_date, ctx.strategy.name, ctx.label):
            ledger.record_signals(session, last_date, ctx.strategy.name, targets, prices, ctx.label)

        account = load_account_state(ctx, session)
        open_buys = {o.symbol for o in ctx.broker.get_open_orders() if o.side == Side.BUY}
        exclude = open_buys | ledger.open_proposal_symbols(session, ctx.label)
        intents = plan_intents(
            targets,
            prices,
            account,
            ctx.limits,
            universe,
            last_date,
            settings.client_order_prefix,
            exclude=exclude,
        )

        exits = [i for i in intents if i.kind == IntentKind.EXIT]
        engaged = killswitch.is_engaged(session)
        used_ids = ledger.used_client_order_ids(session)
        accepted_entries = 0
        for intent in intents:
            if ledger.proposal_exists(session, intent.client_order_id):
                continue
            ai = None
            if intent.kind == IntentKind.ENTRY and settings.ai_mode != AIMode.OFF:
                ai = review_with_budget(ctx, session, intent.symbol, last_date)
            risk_ctx = RiskContext(
                now=ctx.now(),
                universe=set(universe),
                kill_switch_engaged=engaged,
                used_client_order_ids=used_ids,
                enforce_time_window=False,
                pending_new_positions=accepted_entries,
                pending_exit_positions=len(exits),
                extra_buying_power=sum(e.notional for e in exits),
            )
            violations = list(check_order(intent, account, ctx.limits, risk_ctx).violations)
            if (
                ai is not None
                and settings.ai_mode == AIMode.VETO
                and ai.rating in settings.ai_veto_rating_set
            ):
                violations.append(Violation(code="ai_veto", message=f"AI rated {intent.symbol} {ai.rating}."))
            if violations:
                status = ProposalStatus.BLOCKED
            elif settings.auto_approve:
                status = ProposalStatus.APPROVED
            else:
                status = ProposalStatus.PENDING
            row = ledger.create_proposal(
                session,
                intent,
                last_date,
                prices.get(intent.symbol, intent.limit_price),
                status,
                violations,
                ctx.label,
                ai,
                at=ctx.now(),
            )
            rows.append(row)
            if status != ProposalStatus.BLOCKED and intent.kind == IntentKind.ENTRY:
                accepted_entries += 1

        ledger.set_state(
            session,
            "last_nightly_run",
            {"at": ctx.now().isoformat(), "as_of": last_date.isoformat(), "proposals": len(rows)},
        )
        ledger.audit(session, "nightly_run", as_of=last_date, proposals=[r.id for r in rows])
        result.proposal_ids = [r.id for r in rows]
        result.pending = sum(r.status == ProposalStatus.PENDING for r in rows)
        result.approved = sum(r.status == ProposalStatus.APPROVED for r in rows)
        result.blocked = sum(r.status == ProposalStatus.BLOCKED for r in rows)
        notify_proposals(ctx, rows)
    return result
