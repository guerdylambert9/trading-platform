"""Domain objects shared by the strategy, risk, broker and service layers."""

from __future__ import annotations

from datetime import date, datetime
from enum import StrEnum

from pydantic import BaseModel, Field


class Side(StrEnum):
    BUY = "buy"
    SELL = "sell"


class IntentKind(StrEnum):
    ENTRY = "entry"
    EXIT = "exit"


class ProposalStatus(StrEnum):
    PENDING = "pending"  # waiting for your approval
    APPROVED = "approved"  # approved, waiting for the morning submission
    REJECTED = "rejected"  # you said no
    BLOCKED = "blocked"  # failed a risk check or an AI veto
    SUBMITTED = "submitted"  # sent to the broker
    FILLED = "filled"
    CANCELED = "canceled"  # canceled, expired or rejected at the broker
    EXPIRED = "expired"  # never submitted in time
    DRY_RUN = "dry_run"  # passed every check, but DRY_RUN=true kept it from the broker
    ERROR = "error"


OPEN_PROPOSAL_STATUSES = {ProposalStatus.PENDING, ProposalStatus.APPROVED}

OPEN_ORDER_STATUSES = {
    "new",
    "accepted",
    "pending_new",
    "partially_filled",
    "held",
    "accepted_for_bidding",
    "pending_replace",
}


class Position(BaseModel):
    symbol: str
    qty: float
    avg_entry_price: float
    current_price: float

    @property
    def market_value(self) -> float:
        return self.qty * self.current_price


class AccountInfo(BaseModel):
    equity: float
    cash: float
    buying_power: float
    last_equity: float  # equity at the previous close


class AccountState(BaseModel):
    equity: float
    cash: float
    buying_power: float
    day_start_equity: float
    peak_equity: float
    positions: dict[str, Position] = Field(default_factory=dict)

    @property
    def drawdown_pct(self) -> float:
        if self.peak_equity <= 0:
            return 0.0
        return max(0.0, (self.peak_equity - self.equity) / self.peak_equity * 100)

    @property
    def day_pnl_pct(self) -> float:
        if self.day_start_equity <= 0:
            return 0.0
        return (self.equity - self.day_start_equity) / self.day_start_equity * 100

    def held_symbols(self) -> set[str]:
        return {symbol for symbol, position in self.positions.items() if position.qty > 0}


class OrderIntent(BaseModel):
    symbol: str
    side: Side
    kind: IntentKind
    qty: int
    limit_price: float
    stop_price: float | None = None
    source: str = "rules"  # rules | manual | ai (the risk engine always refuses ai)
    reason: str = ""
    client_order_id: str

    @property
    def notional(self) -> float:
        return self.qty * self.limit_price


class BrokerOrder(BaseModel):
    id: str
    client_order_id: str
    symbol: str
    side: Side
    qty: float
    status: str
    filled_qty: float = 0.0
    filled_avg_price: float | None = None
    limit_price: float | None = None
    stop_price: float | None = None
    order_type: str = "limit"
    order_class: str = "simple"
    submitted_at: datetime | None = None
    parent_id: str | None = None

    @property
    def is_open(self) -> bool:
        return self.status in OPEN_ORDER_STATUSES

    @property
    def is_protective_stop(self) -> bool:
        return self.side == Side.SELL and self.stop_price is not None


class MarketClock(BaseModel):
    timestamp: datetime
    is_open: bool
    next_open: datetime
    next_close: datetime
    session_open: datetime | None = None  # today's regular session, when today is a trading day
    session_close: datetime | None = None


class Violation(BaseModel):
    code: str
    message: str


class RiskDecision(BaseModel):
    approved: bool
    violations: list[Violation] = Field(default_factory=list)


AI_RATINGS = ("buy", "overweight", "hold", "underweight", "sell")


class AIDecision(BaseModel):
    symbol: str
    as_of: date
    rating: str = "no_opinion"  # one of AI_RATINGS, or no_opinion
    summary: str = ""
    model: str = ""
    cost_usd: float | None = None
