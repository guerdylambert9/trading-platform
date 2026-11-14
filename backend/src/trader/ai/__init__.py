from __future__ import annotations

from typing import TYPE_CHECKING

from trader.ai.base import AIResearcher, NullResearcher, parse_rating

if TYPE_CHECKING:
    from trader.config import Settings


def get_researcher(settings: Settings) -> AIResearcher:
    name = settings.ai_researcher.strip().lower()
    if name in ("", "null", "none"):
        return NullResearcher()
    if name == "tradingagents":
        from trader.ai.tradingagents_adapter import TradingAgentsResearcher

        return TradingAgentsResearcher()
    raise ValueError(f"Unknown AI_RESEARCHER {settings.ai_researcher!r}. Use 'null' or 'tradingagents'.")


__all__ = ["AIResearcher", "NullResearcher", "get_researcher", "parse_rating"]
