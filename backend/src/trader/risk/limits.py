"""Risk limits shared by the planner, the risk engine and the backtester."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from trader.config import Settings


@dataclass(frozen=True)
class RiskLimits:
    risk_per_trade_pct: float = 1.0
    stop_loss_pct: float = 8.0
    max_position_pct: float = 10.0
    max_open_positions: int = 8
    daily_loss_limit_pct: float = 2.0
    max_drawdown_pct: float = 10.0
    max_orders_per_day: int = 10
    no_trade_after_open_min: int = 15
    no_trade_before_close_min: int = 15
    entry_limit_buffer_pct: float = 0.2

    @classmethod
    def from_settings(cls, settings: Settings) -> RiskLimits:
        return cls(
            risk_per_trade_pct=settings.risk_per_trade_pct,
            stop_loss_pct=settings.stop_loss_pct,
            max_position_pct=settings.max_position_pct,
            max_open_positions=settings.max_open_positions,
            daily_loss_limit_pct=settings.daily_loss_limit_pct,
            max_drawdown_pct=settings.max_drawdown_pct,
            max_orders_per_day=settings.max_orders_per_day,
            no_trade_after_open_min=settings.no_trade_after_open_min,
            no_trade_before_close_min=settings.no_trade_before_close_min,
            entry_limit_buffer_pct=settings.entry_limit_buffer_pct,
        )

    def max_entry_fraction(self) -> float:
        """Largest share of equity a single new position may take.

        Two caps apply: the position-size limit, and the size at which hitting the stop
        would lose exactly risk_per_trade_pct of equity.
        """
        cap = self.max_position_pct / 100
        if self.stop_loss_pct > 0:
            cap = min(cap, self.risk_per_trade_pct / self.stop_loss_pct)
        return cap

    def as_dict(self) -> dict[str, Any]:
        return asdict(self) | {"max_entry_fraction": self.max_entry_fraction()}
