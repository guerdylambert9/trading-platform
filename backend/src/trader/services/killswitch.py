"""Kill switch: one action stops all new orders until you release it.

Engaging it cancels pending entries and any other open orders, but leaves protective stop
orders in place, so open positions stay protected while you review.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from sqlalchemy.orm import Session

from trader import ledger

if TYPE_CHECKING:
    from trader.services.context import AppContext

KEY = "kill_switch"
DEFAULT_STATE: dict[str, Any] = {"engaged": False, "reason": None, "at": None, "by": None}


def state(session: Session) -> dict[str, Any]:
    return dict(ledger.get_state(session, KEY, DEFAULT_STATE) or DEFAULT_STATE)


def is_engaged(session: Session) -> bool:
    return bool(state(session).get("engaged"))


def engage(ctx: AppContext, session: Session, reason: str, by: str) -> int:
    ledger.set_state(session, KEY, {"engaged": True, "reason": reason, "at": ctx.now().isoformat(), "by": by})
    canceled = 0
    try:
        for order in ctx.broker.get_open_orders():
            if order.is_protective_stop:
                continue
            ctx.broker.cancel_order(order.id)
            canceled += 1
    except Exception as exc:  # keep the switch engaged even if the broker call fails
        ledger.audit(session, "kill_switch_cancel_failed", error=str(exc))
    ledger.audit(session, "kill_switch_engaged", reason=reason, by=by, canceled=canceled)
    ctx.notify(
        f"KILL SWITCH ENGAGED ({by}): {reason}. Canceled {canceled} open order(s); protective stops kept. "
        "No new orders until you release it."
    )
    return canceled


def release(ctx: AppContext, session: Session, by: str) -> None:
    ledger.set_state(session, KEY, {"engaged": False, "reason": None, "at": ctx.now().isoformat(), "by": by})
    ledger.audit(session, "kill_switch_released", by=by)
    ctx.notify(f"Kill switch released by {by}. New orders are allowed again.")
