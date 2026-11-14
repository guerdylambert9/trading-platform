from trader.strategies.base import Strategy
from trader.strategies.momentum import Momentum
from trader.strategies.trend import TrendFollowing

STRATEGIES: dict[str, type[Strategy]] = {
    TrendFollowing.name: TrendFollowing,
    Momentum.name: Momentum,
}


def get_strategy(name: str) -> Strategy:
    try:
        return STRATEGIES[name]()
    except KeyError:
        known = ", ".join(sorted(STRATEGIES))
        raise ValueError(f"Unknown strategy {name!r}. Choose one of: {known}.") from None


__all__ = ["STRATEGIES", "Momentum", "Strategy", "TrendFollowing", "get_strategy"]
