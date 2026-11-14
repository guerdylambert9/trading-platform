"""Adapter for TradingAgents (github.com/TauricResearch/TradingAgents), an optional install.

It runs a multi-agent LLM "trading desk" on one ticker and date and returns a five-tier rating.
Expect many LLM calls per decision: keep AI_MAX_CALLS_PER_DAY low and set a spending cap at
your LLM provider. Ratings are logged before outcomes are known so Gate 3 can score them.
"""

from __future__ import annotations

from datetime import date
from typing import Any

from trader.ai.base import parse_rating
from trader.models import AIDecision

INSTALL_HINT = "pip install git+https://github.com/TauricResearch/TradingAgents.git"


class TradingAgentsResearcher:
    name = "tradingagents"

    def __init__(self, config_overrides: dict[str, Any] | None = None) -> None:
        try:
            from tradingagents.default_config import DEFAULT_CONFIG
            from tradingagents.graph.trading_graph import TradingAgentsGraph
        except ImportError as exc:  # pragma: no cover - depends on an optional install
            raise RuntimeError(f"TradingAgents is not installed. Install it with: {INSTALL_HINT}") from exc
        config = DEFAULT_CONFIG.copy()
        config.update(config_overrides or {})
        self._graph = TradingAgentsGraph(debug=False, config=config)
        self._model = f"{config.get('deep_think_llm', '?')} / {config.get('quick_think_llm', '?')}"

    def review(self, symbol: str, as_of: date) -> AIDecision:  # pragma: no cover - needs LLM access
        _, decision = self._graph.propagate(symbol, as_of.isoformat())
        text = str(decision)
        return AIDecision(
            symbol=symbol, as_of=as_of, rating=parse_rating(text), summary=text[:2000], model=self._model
        )
