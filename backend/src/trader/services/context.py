"""Everything a job needs, wired from settings (tests swap in fakes)."""

from __future__ import annotations

import logging
from collections.abc import Callable, Iterator, Mapping
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy.orm import Session, sessionmaker

from trader import ledger
from trader.ai import AIResearcher, get_researcher
from trader.broker import Broker, FakeBroker, get_broker
from trader.config import Settings, get_settings
from trader.data import BarSource, get_bar_source
from trader.db import init_db, make_engine, make_session_factory
from trader.notify import Notifier, get_notifier
from trader.notify.telegram import Buttons
from trader.risk.limits import RiskLimits
from trader.strategies import Strategy, get_strategy
from trader.utils import NY, local_date, utcnow

log = logging.getLogger(__name__)


@dataclass
class AppContext:
    settings: Settings
    session_factory: sessionmaker[Session]
    broker: Broker
    bars: BarSource
    strategy: Strategy
    researcher: AIResearcher
    notifier: Notifier
    now_fn: Callable[[], datetime] = utcnow
    scheduler_running: bool = False

    @property
    def limits(self) -> RiskLimits:
        return RiskLimits.from_settings(self.settings)

    @property
    def tz(self) -> ZoneInfo:
        return ZoneInfo(self.settings.timezone)

    @property
    def label(self) -> str:
        return self.settings.account_label

    def now(self) -> datetime:
        return self.now_fn()

    def today(self) -> date:
        return local_date(self.now(), self.tz)

    @contextmanager
    def session(self) -> Iterator[Session]:
        session = self.session_factory()
        try:
            yield session
            session.commit()
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()

    def notify(self, text: str, buttons: Buttons | None = None) -> None:
        try:
            self.notifier.send(text, buttons)
        except Exception:
            log.exception("Notification failed: %s", text[:120])

    def sync_fake_prices(self, prices: Mapping[str, float]) -> None:
        if isinstance(self.broker, FakeBroker):
            self.broker.set_prices(prices)


def _latest_close_lookup(bars: BarSource) -> Callable[[str], float | None]:
    def lookup(symbol: str) -> float | None:
        end = datetime.now(NY).date()
        try:
            closes = bars.get_closes([symbol], end - timedelta(days=14), end)
        except Exception:
            return None
        if symbol not in closes.columns:
            return None
        series = closes[symbol].dropna()
        return float(series.iloc[-1]) if len(series) else None

    return lookup


def build_context(
    settings: Settings | None = None,
    *,
    broker: Broker | None = None,
    bars: BarSource | None = None,
    strategy: Strategy | None = None,
    researcher: AIResearcher | None = None,
    notifier: Notifier | None = None,
    now_fn: Callable[[], datetime] | None = None,
) -> AppContext:
    settings = settings or get_settings()
    engine = make_engine(settings.database_url)
    init_db(engine)
    session_factory = make_session_factory(engine)
    with session_factory() as session:
        ledger.claim_ledger(session, settings.mode_label, settings.account_label)
        session.commit()
    bars = bars or get_bar_source(settings)
    broker = broker or get_broker(settings, price_source=_latest_close_lookup(bars))
    return AppContext(
        settings=settings,
        session_factory=session_factory,
        broker=broker,
        bars=bars,
        strategy=strategy or get_strategy(settings.strategy),
        researcher=researcher or get_researcher(settings),
        notifier=notifier or get_notifier(settings),
        now_fn=now_fn or utcnow,
    )
