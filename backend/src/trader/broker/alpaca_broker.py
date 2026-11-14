"""Alpaca Trading API adapter (paper or live, set by TRADING_MODE).

Entries go out as OTO orders: a limit buy that, once filled, leaves a stop-loss sell resting
at Alpaca. They use GTC so the stop outlives the first day; the after-close reconciliation
cancels any entry that did not fill, so entries still behave like day orders.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Any

from alpaca.common.exceptions import APIError
from alpaca.data.enums import DataFeed
from alpaca.data.historical import StockHistoricalDataClient
from alpaca.data.requests import StockLatestTradeRequest
from alpaca.trading.client import TradingClient
from alpaca.trading.enums import OrderClass, OrderSide, QueryOrderStatus, TimeInForce
from alpaca.trading.requests import GetCalendarRequest, GetOrdersRequest, LimitOrderRequest, StopLossRequest

from trader.models import AccountInfo, BrokerOrder, MarketClock, OrderIntent, Position, Side
from trader.utils import NY


def _num(value: Any, default: float | None = 0.0) -> float | None:
    if value is None:
        return default
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _text(value: Any) -> str:
    if value is None:
        return ""
    return str(getattr(value, "value", value))


def _as_ny(moment: datetime) -> datetime:
    return moment.replace(tzinfo=NY) if moment.tzinfo is None else moment.astimezone(NY)


class AlpacaBroker:
    def __init__(self, api_key: str, secret_key: str, paper: bool = True, latest_feed: str = "iex") -> None:
        if not api_key or not secret_key:
            raise ValueError("Set ALPACA_API_KEY and ALPACA_SECRET_KEY to use BROKER=alpaca.")
        self.paper = paper
        self.trading = TradingClient(api_key, secret_key, paper=paper)
        self.data = StockHistoricalDataClient(api_key, secret_key)
        self.latest_feed = DataFeed(latest_feed)

    def get_account(self) -> AccountInfo:
        account = self.trading.get_account()
        equity = _num(account.equity) or 0.0
        return AccountInfo(
            equity=equity,
            cash=_num(account.cash) or 0.0,
            buying_power=_num(account.buying_power) or 0.0,
            last_equity=_num(account.last_equity, equity) or equity,
        )

    def get_positions(self) -> list[Position]:
        return [
            Position(
                symbol=p.symbol,
                qty=_num(p.qty) or 0.0,
                avg_entry_price=_num(p.avg_entry_price) or 0.0,
                current_price=_num(p.current_price) or 0.0,
            )
            for p in self.trading.get_all_positions()
        ]

    def get_open_orders(self, symbol: str | None = None) -> list[BrokerOrder]:
        request = GetOrdersRequest(
            status=QueryOrderStatus.OPEN, symbols=[symbol] if symbol else None, nested=False, limit=500
        )
        return [self._order(o) for o in self.trading.get_orders(filter=request)]

    def get_orders_since(self, since: datetime) -> list[BrokerOrder]:
        request = GetOrdersRequest(status=QueryOrderStatus.ALL, after=since, nested=False, limit=500)
        return [self._order(o) for o in self.trading.get_orders(filter=request)]

    def get_order_by_client_id(self, client_order_id: str) -> BrokerOrder | None:
        try:
            return self._order(self.trading.get_order_by_client_id(client_order_id))
        except APIError as exc:
            if exc.status_code == 404 or "not found" in str(exc).lower():
                return None
            raise

    def submit_limit_order(self, intent: OrderIntent) -> BrokerOrder:
        side = OrderSide.BUY if intent.side == Side.BUY else OrderSide.SELL
        if intent.stop_price is not None:
            request = LimitOrderRequest(
                symbol=intent.symbol,
                qty=intent.qty,
                side=side,
                time_in_force=TimeInForce.GTC,
                limit_price=intent.limit_price,
                client_order_id=intent.client_order_id,
                order_class=OrderClass.OTO,
                stop_loss=StopLossRequest(stop_price=intent.stop_price),
            )
        else:
            request = LimitOrderRequest(
                symbol=intent.symbol,
                qty=intent.qty,
                side=side,
                time_in_force=TimeInForce.DAY,
                limit_price=intent.limit_price,
                client_order_id=intent.client_order_id,
            )
        return self._order(self.trading.submit_order(order_data=request))

    def cancel_order(self, order_id: str) -> None:
        self.trading.cancel_order_by_id(order_id)

    def latest_price(self, symbol: str) -> float:
        request = StockLatestTradeRequest(symbol_or_symbols=symbol, feed=self.latest_feed)
        trades = self.data.get_stock_latest_trade(request)
        return float(trades[symbol].price)

    def clock(self) -> MarketClock:
        clock = self.trading.get_clock()
        today: date = clock.timestamp.astimezone(NY).date()
        session_open = session_close = None
        days = self.trading.get_calendar(GetCalendarRequest(start=today, end=today))
        if days and days[0].date == today:
            session_open = _as_ny(days[0].open)
            session_close = _as_ny(days[0].close)
        return MarketClock(
            timestamp=clock.timestamp,
            is_open=clock.is_open,
            next_open=clock.next_open,
            next_close=clock.next_close,
            session_open=session_open,
            session_close=session_close,
        )

    @staticmethod
    def _order(order: Any) -> BrokerOrder:
        return BrokerOrder(
            id=str(order.id),
            client_order_id=order.client_order_id,
            symbol=order.symbol or "",
            side=Side.BUY if _text(order.side) == "buy" else Side.SELL,
            qty=_num(order.qty) or 0.0,
            status=_text(order.status),
            filled_qty=_num(order.filled_qty) or 0.0,
            filled_avg_price=_num(order.filled_avg_price, None),
            limit_price=_num(order.limit_price, None),
            stop_price=_num(order.stop_price, None),
            order_type=_text(order.order_type or order.type) or "limit",
            order_class=_text(order.order_class) or "simple",
            submitted_at=order.submitted_at,
        )
