"""Dashboard API. Everything except /health needs the bearer token when API_TOKEN is set."""

from __future__ import annotations

import hmac
from dataclasses import asdict
from typing import TYPE_CHECKING, Annotated, Any

from fastapi import APIRouter, Depends, Header, HTTPException, Query
from fastapi.encoders import jsonable_encoder

from trader import __version__, ledger
from trader.api.schemas import (
    AIDecisionOut,
    EquityPoint,
    KillSwitchIn,
    OrderOut,
    PositionOut,
    ProposalOut,
    ReconciliationOut,
    SignalOut,
)
from trader.services import killswitch
from trader.services.account import load_account_state
from trader.services.approvals import InvalidTransitionError, ProposalNotFoundError, decide_proposal
from trader.services.execution import submit_approved
from trader.services.pipeline import run_nightly
from trader.services.reconcile import reconcile

if TYPE_CHECKING:
    from trader.services.context import AppContext


def build_router(ctx: AppContext) -> APIRouter:
    def require_token(authorization: Annotated[str | None, Header()] = None) -> None:
        expected = ctx.settings.api_token
        if not expected:
            return
        supplied = (authorization or "").encode()
        if not hmac.compare_digest(supplied, f"Bearer {expected}".encode()):
            raise HTTPException(status_code=401, detail="Missing or wrong API token.")

    router = APIRouter()

    @router.get("/health")
    def health() -> dict[str, Any]:
        return {"ok": True, "version": __version__}

    api = APIRouter(dependencies=[Depends(require_token)])

    @api.get("/status")
    def status() -> dict[str, Any]:
        settings = ctx.settings
        account: dict[str, Any] | None = None
        clock: dict[str, Any] | None = None
        broker_error = None
        with ctx.session() as session:
            kill = killswitch.state(session)
            last_runs = {
                name: ledger.get_state(session, f"last_{name}_run")
                for name in ("nightly", "submit", "reconcile")
            }
            recent = ledger.recent_reconciliations(session, ctx.label, limit=1)
            pending = len(ledger.list_proposals(session, ctx.label, status="pending", limit=500))
            try:
                state = load_account_state(ctx, session)
                account = {
                    "equity": state.equity,
                    "cash": state.cash,
                    "buying_power": state.buying_power,
                    "day_pnl_pct": state.day_pnl_pct,
                    "drawdown_pct": state.drawdown_pct,
                    "peak_equity": state.peak_equity,
                    "open_positions": len(state.held_symbols()),
                }
                market = ctx.broker.clock()
                clock = {
                    "is_open": market.is_open,
                    "next_open": market.next_open,
                    "next_close": market.next_close,
                }
            except Exception as exc:  # show the dashboard even if the broker is unreachable
                broker_error = str(exc)
        return jsonable_encoder(
            {
                "mode": settings.mode_label,
                "broker": str(settings.broker),
                "trading_mode": str(settings.trading_mode),
                "dry_run": settings.dry_run,
                "account_label": ctx.label,
                "strategy": ctx.strategy.describe(),
                "universe": settings.universe_list,
                "benchmark": settings.benchmark_symbol,
                "ai_mode": str(settings.ai_mode),
                "auto_approve": settings.auto_approve,
                "kill_switch": kill,
                "account": account,
                "clock": clock,
                "broker_error": broker_error,
                "pending_proposals": pending,
                "scheduler_running": ctx.scheduler_running,
                "last_runs": last_runs,
                "last_reconciliation": ReconciliationOut.model_validate(recent[0]).model_dump(mode="json")
                if recent
                else None,
            }
        )

    @api.get("/proposals", response_model=list[ProposalOut])
    def proposals(
        status: str | None = None, limit: Annotated[int, Query(ge=1, le=500)] = 100
    ) -> list[ProposalOut]:
        with ctx.session() as session:
            return [
                ProposalOut.model_validate(row)
                for row in ledger.list_proposals(session, ctx.label, status, limit)
            ]

    def decide(proposal_id: int, approve: bool) -> ProposalOut:
        with ctx.session() as session:
            try:
                row = decide_proposal(
                    session, proposal_id, approve, by="dashboard", label=ctx.label, at=ctx.now()
                )
            except ProposalNotFoundError as exc:
                raise HTTPException(status_code=404, detail=str(exc)) from exc
            except InvalidTransitionError as exc:
                raise HTTPException(status_code=409, detail=str(exc)) from exc
            return ProposalOut.model_validate(row)

    @api.post("/proposals/{proposal_id}/approve", response_model=ProposalOut)
    def approve(proposal_id: int) -> ProposalOut:
        return decide(proposal_id, True)

    @api.post("/proposals/{proposal_id}/reject", response_model=ProposalOut)
    def reject(proposal_id: int) -> ProposalOut:
        return decide(proposal_id, False)

    @api.get("/positions", response_model=list[PositionOut])
    def positions() -> list[PositionOut]:
        held = ctx.broker.get_positions()
        stops = {o.symbol: o.stop_price for o in ctx.broker.get_open_orders() if o.is_protective_stop}
        equity = ctx.broker.get_account().equity
        out = []
        for position in held:
            cost = position.qty * position.avg_entry_price
            value = position.market_value
            out.append(
                PositionOut(
                    symbol=position.symbol,
                    qty=position.qty,
                    avg_entry_price=position.avg_entry_price,
                    current_price=position.current_price,
                    market_value=value,
                    unrealized_pl=value - cost,
                    unrealized_pl_pct=(value / cost - 1) * 100 if cost else 0.0,
                    weight_pct=value / equity * 100 if equity else 0.0,
                    stop_price=stops.get(position.symbol),
                    protected=position.symbol in stops,
                )
            )
        return out

    @api.get("/orders", response_model=list[OrderOut])
    def orders(limit: Annotated[int, Query(ge=1, le=500)] = 100) -> list[OrderOut]:
        with ctx.session() as session:
            return [OrderOut.model_validate(row) for row in ledger.recent_orders(session, ctx.label, limit)]

    @api.get("/signals", response_model=list[SignalOut])
    def signals() -> list[SignalOut]:
        with ctx.session() as session:
            return [SignalOut.model_validate(row) for row in ledger.latest_signals(session, ctx.label)]

    @api.get("/equity", response_model=list[EquityPoint])
    def equity() -> list[EquityPoint]:
        with ctx.session() as session:
            rows = ledger.equity_history(session, ctx.label)
        base = next((row for row in rows if row.benchmark_price), None)
        scale = base.equity / base.benchmark_price if base and base.benchmark_price else None
        return [
            EquityPoint(
                as_of=row.as_of,
                equity=row.equity,
                benchmark=row.benchmark_price * scale if scale and row.benchmark_price else None,
            )
            for row in rows
        ]

    @api.get("/risk")
    def risk() -> dict[str, Any]:
        settings = ctx.settings
        usage: dict[str, Any] = {}
        with ctx.session() as session:
            usage["orders_today"] = ledger.orders_submitted_on(session, ctx.today(), ctx.tz, ctx.label)
            try:
                state = load_account_state(ctx, session)
                usage |= {
                    "open_positions": len(state.held_symbols()),
                    "drawdown_pct": state.drawdown_pct,
                    "day_pnl_pct": state.day_pnl_pct,
                }
            except Exception:
                usage |= {"open_positions": None, "drawdown_pct": None, "day_pnl_pct": None}
        return {
            "limits": ctx.limits.as_dict(),
            "usage": usage,
            "max_gap_pct": settings.max_gap_pct,
            "auto_approve": settings.auto_approve,
        }

    @api.get("/ai-decisions", response_model=list[AIDecisionOut])
    def ai_decisions(limit: Annotated[int, Query(ge=1, le=500)] = 50) -> list[AIDecisionOut]:
        with ctx.session() as session:
            return [
                AIDecisionOut.model_validate(row)
                for row in ledger.recent_ai_decisions(session, ctx.label, limit)
            ]

    @api.get("/reconciliations", response_model=list[ReconciliationOut])
    def reconciliations(limit: Annotated[int, Query(ge=1, le=100)] = 10) -> list[ReconciliationOut]:
        with ctx.session() as session:
            return [
                ReconciliationOut.model_validate(row)
                for row in ledger.recent_reconciliations(session, ctx.label, limit)
            ]

    @api.post("/kill-switch")
    def kill_switch(body: KillSwitchIn) -> dict[str, Any]:
        with ctx.session() as session:
            if body.engage:
                killswitch.engage(ctx, session, body.reason or "Engaged from the dashboard", by="dashboard")
            else:
                if (body.confirm or "").strip().upper() != "RELEASE":
                    raise HTTPException(status_code=400, detail="Type RELEASE to confirm.")
                killswitch.release(ctx, session, by="dashboard")
            return killswitch.state(session)

    @api.post("/jobs/{name}")
    def run_job(name: str, force: bool = False) -> dict[str, Any]:
        if name == "nightly":
            result: Any = run_nightly(ctx, force=force)
        elif name == "submit":
            result = submit_approved(ctx)
        elif name == "reconcile":
            result = reconcile(ctx)
        else:
            raise HTTPException(status_code=404, detail="Unknown job. Use nightly, submit or reconcile.")
        return {"job": name, "result": jsonable_encoder(asdict(result))}

    router.include_router(api)
    return router
