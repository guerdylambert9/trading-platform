"""Read and write the ledger: signals, proposals, orders, equity, AI decisions, state and audit."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import date, datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from trader.db import (
    AIDecisionRow,
    AuditRow,
    EquitySnapshotRow,
    OrderRow,
    ProposalRow,
    ReconciliationRow,
    SignalRow,
    StateRow,
)
from trader.models import (
    AIDecision,
    BrokerOrder,
    IntentKind,
    OrderIntent,
    ProposalStatus,
    Violation,
)
from trader.utils import is_number, local_date, utcnow

# ---------------------------------------------------------------- state and audit


def get_state(session: Session, key: str, default: Any = None) -> Any:
    row = session.get(StateRow, key)
    return default if row is None else row.value


OWNER_KEY = "ledger_owner"


class LedgerOwnerError(RuntimeError):
    """The database already holds another account's ledger."""


def claim_ledger(session: Session, mode: str, account: str) -> None:
    """Tie a database to one account, so demo, paper and live records can never mix."""
    owner = {"mode": mode, "account": account}
    stored = get_state(session, OWNER_KEY)
    if stored is None:
        set_state(session, OWNER_KEY, owner)
    elif stored != owner:
        raise LedgerOwnerError(
            f"This database holds the ledger of {stored.get('mode')} account {stored.get('account')}, "
            f"but the settings are for {mode} account {account}. Give each account its own DATABASE_URL."
        )


def ledger_owner(url: str) -> dict[str, Any] | None:
    """The owner recorded in an existing database, without creating anything."""
    from sqlalchemy import inspect

    from trader.db import make_engine

    engine = make_engine(url)
    try:
        if not inspect(engine).has_table(StateRow.__tablename__):
            return None
        with Session(engine) as session:
            return get_state(session, OWNER_KEY)
    finally:
        engine.dispose()


def set_state(session: Session, key: str, value: Any) -> None:
    row = session.get(StateRow, key)
    if row is None:
        session.add(StateRow(key=key, value=jsonable(value), updated_at=utcnow()))
    else:
        row.value = jsonable(value)
        row.updated_at = utcnow()
    session.flush()


def audit(session: Session, event: str, **details: Any) -> None:
    session.add(AuditRow(event=event, details=jsonable(details)))


def jsonable(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {str(k): jsonable(v) for k, v in value.items()}
    if isinstance(value, list | tuple | set):
        return [jsonable(v) for v in value]
    if isinstance(value, datetime | date):
        return value.isoformat()
    if hasattr(value, "model_dump"):
        return value.model_dump(mode="json")
    if isinstance(value, float) and not is_number(value):
        return None
    if value is None or isinstance(value, str | int | float | bool):
        return value
    return str(value)


# ---------------------------------------------------------------- signals


def signals_exist(session: Session, as_of: date, strategy: str, label: str) -> bool:
    stmt = (
        select(func.count())
        .select_from(SignalRow)
        .where(SignalRow.as_of == as_of, SignalRow.strategy == strategy, SignalRow.account_label == label)
    )
    return (session.scalar(stmt) or 0) > 0


def record_signals(
    session: Session,
    as_of: date,
    strategy: str,
    targets: Mapping[str, float],
    prices: Mapping[str, float],
    label: str,
) -> None:
    for symbol, weight in targets.items():
        price = prices.get(symbol)
        session.add(
            SignalRow(
                as_of=as_of,
                strategy=strategy,
                symbol=symbol,
                target_weight=float(weight) if is_number(weight) else 0.0,
                price=float(price) if is_number(price) else None,
                account_label=label,
            )
        )
    session.flush()


def latest_signals(session: Session, label: str) -> list[SignalRow]:
    latest = session.scalar(select(func.max(SignalRow.as_of)).where(SignalRow.account_label == label))
    if latest is None:
        return []
    stmt = (
        select(SignalRow)
        .where(SignalRow.account_label == label, SignalRow.as_of == latest)
        .order_by(SignalRow.target_weight.desc(), SignalRow.symbol)
    )
    return list(session.scalars(stmt))


# ---------------------------------------------------------------- proposals


def create_proposal(
    session: Session,
    intent: OrderIntent,
    as_of: date,
    est_price: float,
    status: ProposalStatus,
    violations: list[Violation],
    label: str,
    ai: AIDecision | None = None,
    at: datetime | None = None,
) -> ProposalRow:
    row = ProposalRow(
        created_at=at or utcnow(),
        as_of=as_of,
        account_label=label,
        symbol=intent.symbol,
        side=str(intent.side),
        kind=str(intent.kind),
        qty=intent.qty,
        est_price=float(est_price),
        limit_price=intent.limit_price,
        stop_price=intent.stop_price,
        reason=intent.reason,
        source=intent.source,
        status=str(status),
        violations=[v.model_dump() for v in violations],
        ai_rating=ai.rating if ai else None,
        ai_summary=ai.summary if ai else None,
        client_order_id=intent.client_order_id,
    )
    session.add(row)
    session.flush()
    return row


def proposal_exists(session: Session, client_order_id: str) -> bool:
    stmt = select(func.count()).select_from(ProposalRow).where(ProposalRow.client_order_id == client_order_id)
    return (session.scalar(stmt) or 0) > 0


def list_proposals(
    session: Session, label: str, status: str | None = None, limit: int = 100
) -> list[ProposalRow]:
    stmt = select(ProposalRow).where(ProposalRow.account_label == label)
    if status:
        stmt = stmt.where(ProposalRow.status == status)
    stmt = stmt.order_by(ProposalRow.id.desc()).limit(limit)
    return list(session.scalars(stmt))


def proposals_with_status(session: Session, label: str, statuses: set[str]) -> list[ProposalRow]:
    stmt = (
        select(ProposalRow)
        .where(ProposalRow.account_label == label, ProposalRow.status.in_([str(s) for s in statuses]))
        .order_by(ProposalRow.id)
    )
    return list(session.scalars(stmt))


def open_proposal_symbols(session: Session, label: str) -> set[str]:
    open_statuses = {ProposalStatus.PENDING, ProposalStatus.APPROVED}
    return {row.symbol for row in proposals_with_status(session, label, open_statuses)}


def approved_unsubmitted(session: Session, label: str) -> list[ProposalRow]:
    """Approved proposals, exits first so their cash is free before entries go out."""
    rows = proposals_with_status(session, label, {ProposalStatus.APPROVED})
    return sorted(rows, key=lambda row: (0 if row.kind == IntentKind.EXIT else 1, row.id))


def expire_stale(session: Session, label: str, today: date, max_age_days: int = 4) -> list[int]:
    cutoff = today - timedelta(days=max_age_days)
    expired = []
    for row in proposals_with_status(session, label, {ProposalStatus.PENDING, ProposalStatus.APPROVED}):
        if row.as_of < cutoff:
            row.status = ProposalStatus.EXPIRED
            row.error = f"Not submitted within {max_age_days} days of its signal."
            expired.append(row.id)
    session.flush()
    return expired


def orders_submitted_on(session: Session, day: date, tz: str | ZoneInfo, label: str) -> int:
    stmt = select(ProposalRow.submitted_at).where(
        ProposalRow.account_label == label,
        ProposalRow.submitted_at.is_not(None),
        ProposalRow.as_of >= day - timedelta(days=10),
    )
    return sum(1 for ts in session.scalars(stmt) if ts is not None and local_date(ts, tz) == day)


# ---------------------------------------------------------------- orders


def used_client_order_ids(session: Session) -> set[str]:
    return set(session.scalars(select(OrderRow.client_order_id)))


def upsert_order(
    session: Session, order: BrokerOrder, label: str, proposal_id: int | None = None
) -> OrderRow:
    row = session.scalar(select(OrderRow).where(OrderRow.client_order_id == order.client_order_id))
    if row is None:
        row = OrderRow(client_order_id=order.client_order_id, account_label=label)
        session.add(row)
    row.broker_order_id = order.id
    row.symbol = order.symbol
    row.side = str(order.side)
    row.qty = order.qty
    row.filled_qty = order.filled_qty
    row.filled_avg_price = order.filled_avg_price
    row.status = order.status
    row.order_class = order.order_class
    row.limit_price = order.limit_price
    if order.stop_price is not None or row.stop_price is None:
        row.stop_price = order.stop_price
    row.submitted_at = order.submitted_at
    row.updated_at = utcnow()
    if proposal_id is not None:
        row.proposal_id = proposal_id
    session.flush()
    return row


def recent_orders(session: Session, label: str, limit: int = 100) -> list[OrderRow]:
    stmt = select(OrderRow).where(OrderRow.account_label == label).order_by(OrderRow.id.desc()).limit(limit)
    return list(session.scalars(stmt))


# ---------------------------------------------------------------- equity


def record_equity(
    session: Session, as_of: date, equity: float, cash: float, benchmark_price: float | None, label: str
) -> None:
    stmt = select(EquitySnapshotRow).where(
        EquitySnapshotRow.as_of == as_of, EquitySnapshotRow.account_label == label
    )
    row = session.scalar(stmt)
    if row is None:
        row = EquitySnapshotRow(as_of=as_of, account_label=label, equity=equity, cash=cash)
        session.add(row)
    row.equity = equity
    row.cash = cash
    row.benchmark_price = benchmark_price
    row.ts = utcnow()
    session.flush()


def equity_history(session: Session, label: str) -> list[EquitySnapshotRow]:
    stmt = (
        select(EquitySnapshotRow)
        .where(EquitySnapshotRow.account_label == label)
        .order_by(EquitySnapshotRow.as_of)
    )
    return list(session.scalars(stmt))


# ---------------------------------------------------------------- AI decisions


def record_ai_decision(session: Session, decision: AIDecision, label: str) -> AIDecisionRow:
    row = AIDecisionRow(
        as_of=decision.as_of,
        symbol=decision.symbol,
        rating=decision.rating,
        summary=decision.summary[:5000],
        model=decision.model[:128],
        cost_usd=decision.cost_usd,
        account_label=label,
    )
    session.add(row)
    session.flush()
    return row


def ai_calls_on(session: Session, day: date, label: str) -> int:
    stmt = (
        select(func.count())
        .select_from(AIDecisionRow)
        .where(AIDecisionRow.as_of == day, AIDecisionRow.account_label == label)
    )
    return session.scalar(stmt) or 0


def recent_ai_decisions(session: Session, label: str, limit: int = 100) -> list[AIDecisionRow]:
    stmt = (
        select(AIDecisionRow)
        .where(AIDecisionRow.account_label == label)
        .order_by(AIDecisionRow.id.desc())
        .limit(limit)
    )
    return list(session.scalars(stmt))


# ---------------------------------------------------------------- reconciliation


def record_reconciliation(
    session: Session, ok: bool, mismatches: list[dict[str, Any]], label: str, at: datetime | None = None
) -> ReconciliationRow:
    row = ReconciliationRow(ts=at or utcnow(), ok=ok, mismatches=jsonable(mismatches), account_label=label)
    session.add(row)
    session.flush()
    return row


def recent_reconciliations(session: Session, label: str, limit: int = 20) -> list[ReconciliationRow]:
    stmt = (
        select(ReconciliationRow)
        .where(ReconciliationRow.account_label == label)
        .order_by(ReconciliationRow.id.desc())
        .limit(limit)
    )
    return list(session.scalars(stmt))
