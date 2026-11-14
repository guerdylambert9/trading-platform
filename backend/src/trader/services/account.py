"""Account state as the risk engine sees it: broker balances plus the stored equity peak."""

from __future__ import annotations

from typing import TYPE_CHECKING

from sqlalchemy.orm import Session

from trader import ledger
from trader.models import AccountState

if TYPE_CHECKING:
    from trader.services.context import AppContext

PEAK_KEY = "peak_equity"


def load_account_state(ctx: AppContext, session: Session) -> AccountState:
    info = ctx.broker.get_account()
    positions = {p.symbol: p for p in ctx.broker.get_positions() if p.qty > 0}
    stored_peak = ledger.get_state(session, PEAK_KEY, info.equity)
    peak = max(float(stored_peak or info.equity), info.equity)
    return AccountState(
        equity=info.equity,
        cash=info.cash,
        buying_power=min(info.cash, info.buying_power) if info.cash > 0 else info.buying_power,
        day_start_equity=info.last_equity or info.equity,
        peak_equity=peak,
        positions=positions,
    )
