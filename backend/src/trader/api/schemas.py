"""Response and request models for the dashboard API."""

from __future__ import annotations

from datetime import date, datetime
from typing import Annotated, Any

from pydantic import BaseModel, BeforeValidator, ConfigDict

from trader.utils import as_utc


def _utc(value: Any) -> Any:
    return as_utc(value) if isinstance(value, datetime) else value


UTCDateTime = Annotated[datetime, BeforeValidator(_utc)]


class ORMModel(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class ProposalOut(ORMModel):
    id: int
    created_at: UTCDateTime
    as_of: date
    symbol: str
    side: str
    kind: str
    qty: int
    est_price: float
    limit_price: float
    stop_price: float | None
    reason: str
    source: str
    status: str
    violations: list[dict[str, Any]]
    ai_rating: str | None
    ai_summary: str | None
    client_order_id: str
    decided_at: UTCDateTime | None
    decided_by: str | None
    submitted_at: UTCDateTime | None
    broker_order_id: str | None
    error: str | None


class OrderOut(ORMModel):
    id: int
    client_order_id: str
    broker_order_id: str | None
    proposal_id: int | None
    symbol: str
    side: str
    qty: float
    filled_qty: float
    filled_avg_price: float | None
    status: str
    order_class: str
    limit_price: float | None
    stop_price: float | None
    submitted_at: UTCDateTime | None
    updated_at: UTCDateTime


class SignalOut(ORMModel):
    id: int
    as_of: date
    strategy: str
    symbol: str
    target_weight: float
    price: float | None


class AIDecisionOut(ORMModel):
    id: int
    created_at: UTCDateTime
    as_of: date
    symbol: str
    rating: str
    summary: str
    model: str
    cost_usd: float | None


class ReconciliationOut(ORMModel):
    id: int
    ts: UTCDateTime
    ok: bool
    mismatches: list[dict[str, Any]]


class PositionOut(BaseModel):
    symbol: str
    qty: float
    avg_entry_price: float
    current_price: float
    market_value: float
    unrealized_pl: float
    unrealized_pl_pct: float
    weight_pct: float
    stop_price: float | None
    protected: bool


class EquityPoint(BaseModel):
    as_of: date
    equity: float
    benchmark: float | None


class KillSwitchIn(BaseModel):
    engage: bool
    reason: str = "Engaged from the dashboard"
    confirm: str | None = None
