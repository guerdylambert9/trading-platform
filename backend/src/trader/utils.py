"""Small helpers: price rounding and time zones."""

from __future__ import annotations

import math
from datetime import UTC, date, datetime
from zoneinfo import ZoneInfo

NY = ZoneInfo("America/New_York")


def round_up_cents(value: float) -> float:
    """Round up to the cent (buy limits and stops: never riskier than intended)."""
    return math.ceil(round(value * 100, 6)) / 100


def round_down_cents(value: float) -> float:
    """Round down to the cent (sell limits: stay marketable)."""
    return math.floor(round(value * 100, 6)) / 100


def utcnow() -> datetime:
    return datetime.now(UTC)


def as_utc(value: datetime | None) -> datetime | None:
    """Treat naive datetimes as UTC (SQLite drops the time zone on the way out)."""
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def local_date(value: datetime, tz: str | ZoneInfo = NY) -> date:
    zone = ZoneInfo(tz) if isinstance(tz, str) else tz
    moment = as_utc(value)
    assert moment is not None
    return moment.astimezone(zone).date()


def is_number(value: object) -> bool:
    """True for real, finite numbers (filters out None and NaN)."""
    try:
        number = float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return False
    return math.isfinite(number)
