"""AI research layer (Phase 3). The AI can rank or veto a rules signal; it never places orders."""

from __future__ import annotations

import re
from datetime import date
from typing import Protocol

from trader.models import AIDecision


class AIResearcher(Protocol):
    name: str

    def review(self, symbol: str, as_of: date) -> AIDecision: ...


class NullResearcher:
    """The default: no AI, no opinion, no cost."""

    name = "null"

    def review(self, symbol: str, as_of: date) -> AIDecision:
        return AIDecision(
            symbol=symbol,
            as_of=as_of,
            rating="no_opinion",
            summary="No AI researcher configured.",
            model="none",
        )


_RATINGS = r"(buy|overweight|hold|underweight|sell)"
_LABELLED = [
    re.compile(r"\brating\b\W{0,12}" + _RATINGS + r"\b", re.IGNORECASE),
    re.compile(
        r"\bfinal\s+(?:transaction\s+)?(?:proposal|decision)\b\W{0,12}" + _RATINGS + r"\b", re.IGNORECASE
    ),
]
_ANY = re.compile(r"\b" + _RATINGS + r"\b", re.IGNORECASE)


def parse_rating(text: str) -> str:
    """Pull a five-tier rating out of free text; 'no_opinion' when it is ambiguous."""
    for pattern in _LABELLED:
        match = pattern.search(text)
        if match:
            return match.group(1).lower()
    found = {word.lower() for word in _ANY.findall(text)}
    return found.pop() if len(found) == 1 else "no_opinion"
