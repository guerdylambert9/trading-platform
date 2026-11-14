"""Ledger tables and engine setup. SQLite by default; set DATABASE_URL for Postgres.

Every signal, proposal, order, equity snapshot and AI decision is written here before its
outcome is known, so results can be audited later.
"""

from __future__ import annotations

from datetime import date, datetime
from pathlib import Path
from typing import Any

from sqlalchemy import (
    JSON,
    Boolean,
    Date,
    DateTime,
    Float,
    Integer,
    String,
    Text,
    UniqueConstraint,
    create_engine,
)
from sqlalchemy.engine import Engine, make_url
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column, sessionmaker
from sqlalchemy.pool import StaticPool

from trader.utils import utcnow


class Base(DeclarativeBase):
    pass


class SignalRow(Base):
    __tablename__ = "signals"
    __table_args__ = (UniqueConstraint("as_of", "strategy", "symbol", "account_label", name="uq_signal"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    as_of: Mapped[date] = mapped_column(Date, index=True)
    strategy: Mapped[str] = mapped_column(String(64))
    symbol: Mapped[str] = mapped_column(String(16))
    target_weight: Mapped[float] = mapped_column(Float)
    price: Mapped[float | None] = mapped_column(Float, nullable=True)
    account_label: Mapped[str] = mapped_column(String(8), default="A")


class ProposalRow(Base):
    __tablename__ = "proposals"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    as_of: Mapped[date] = mapped_column(Date, index=True)
    account_label: Mapped[str] = mapped_column(String(8), default="A")
    symbol: Mapped[str] = mapped_column(String(16))
    side: Mapped[str] = mapped_column(String(4))
    kind: Mapped[str] = mapped_column(String(8))
    qty: Mapped[int] = mapped_column(Integer)
    est_price: Mapped[float] = mapped_column(Float)
    limit_price: Mapped[float] = mapped_column(Float)
    stop_price: Mapped[float | None] = mapped_column(Float, nullable=True)
    reason: Mapped[str] = mapped_column(Text, default="")
    source: Mapped[str] = mapped_column(String(16), default="rules")
    status: Mapped[str] = mapped_column(String(16), index=True)
    violations: Mapped[list[Any]] = mapped_column(JSON, default=list)
    ai_rating: Mapped[str | None] = mapped_column(String(16), nullable=True)
    ai_summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    client_order_id: Mapped[str] = mapped_column(String(128), unique=True)
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    decided_by: Mapped[str | None] = mapped_column(String(32), nullable=True)
    submitted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    broker_order_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)


class OrderRow(Base):
    __tablename__ = "orders"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    client_order_id: Mapped[str] = mapped_column(String(128), unique=True)
    broker_order_id: Mapped[str | None] = mapped_column(String(64), index=True, nullable=True)
    proposal_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    account_label: Mapped[str] = mapped_column(String(8), default="A")
    symbol: Mapped[str] = mapped_column(String(16))
    side: Mapped[str] = mapped_column(String(4))
    qty: Mapped[float] = mapped_column(Float)
    filled_qty: Mapped[float] = mapped_column(Float, default=0.0)
    filled_avg_price: Mapped[float | None] = mapped_column(Float, nullable=True)
    status: Mapped[str] = mapped_column(String(32))
    order_class: Mapped[str] = mapped_column(String(16), default="simple")
    limit_price: Mapped[float | None] = mapped_column(Float, nullable=True)
    stop_price: Mapped[float | None] = mapped_column(Float, nullable=True)
    submitted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class EquitySnapshotRow(Base):
    __tablename__ = "equity_snapshots"
    __table_args__ = (UniqueConstraint("as_of", "account_label", name="uq_equity_day"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    as_of: Mapped[date] = mapped_column(Date, index=True)
    ts: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    equity: Mapped[float] = mapped_column(Float)
    cash: Mapped[float] = mapped_column(Float)
    benchmark_price: Mapped[float | None] = mapped_column(Float, nullable=True)
    account_label: Mapped[str] = mapped_column(String(8), default="A")


class AIDecisionRow(Base):
    __tablename__ = "ai_decisions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    as_of: Mapped[date] = mapped_column(Date, index=True)
    symbol: Mapped[str] = mapped_column(String(16))
    rating: Mapped[str] = mapped_column(String(16))
    summary: Mapped[str] = mapped_column(Text, default="")
    model: Mapped[str] = mapped_column(String(128), default="")
    cost_usd: Mapped[float | None] = mapped_column(Float, nullable=True)
    account_label: Mapped[str] = mapped_column(String(8), default="A")


class StateRow(Base):
    __tablename__ = "app_state"

    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    value: Mapped[Any] = mapped_column(JSON)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class AuditRow(Base):
    __tablename__ = "audit_log"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    ts: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    event: Mapped[str] = mapped_column(String(64), index=True)
    details: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)


class ReconciliationRow(Base):
    __tablename__ = "reconciliations"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    ts: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    ok: Mapped[bool] = mapped_column(Boolean)
    mismatches: Mapped[list[Any]] = mapped_column(JSON, default=list)
    account_label: Mapped[str] = mapped_column(String(8), default="A")


class DatabaseDriverError(RuntimeError):
    """The database URL needs a driver that isn't installed."""


def make_engine(url: str) -> Engine:
    if url.startswith("sqlite"):
        parsed = make_url(url)
        database = parsed.database or ""
        kwargs: dict[str, Any] = {"connect_args": {"check_same_thread": False}}
        if database in ("", ":memory:"):
            kwargs["poolclass"] = StaticPool
        else:
            Path(database).expanduser().resolve().parent.mkdir(parents=True, exist_ok=True)
        return create_engine(url, **kwargs)
    try:
        return create_engine(url, pool_pre_ping=True)
    except ModuleNotFoundError as exc:
        raise DatabaseDriverError(
            f"DATABASE_URL needs the {exc.name} driver, which isn't installed. "
            'For Postgres, run: pip install -e ".[postgres]"'
        ) from exc


def init_db(engine: Engine) -> None:
    Base.metadata.create_all(engine)


def make_session_factory(engine: Engine) -> sessionmaker[Session]:
    return sessionmaker(bind=engine, expire_on_commit=False)
