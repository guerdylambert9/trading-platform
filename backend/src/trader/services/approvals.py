"""Approve or reject proposals, from the dashboard, the CLI or Telegram."""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING, Any

from sqlalchemy.orm import Session

from trader import ledger
from trader.db import ProposalRow
from trader.models import ProposalStatus
from trader.utils import utcnow

if TYPE_CHECKING:
    from trader.services.context import AppContext


class ProposalNotFoundError(LookupError):
    pass


class InvalidTransitionError(ValueError):
    pass


def decide_proposal(
    session: Session,
    proposal_id: int,
    approve: bool,
    by: str,
    label: str | None = None,
    at: datetime | None = None,
) -> ProposalRow:
    row = session.get(ProposalRow, proposal_id)
    if row is None or (label is not None and row.account_label != label):
        raise ProposalNotFoundError(f"Proposal #{proposal_id} not found.")
    if row.status != ProposalStatus.PENDING:
        raise InvalidTransitionError(
            f"Proposal #{proposal_id} is {row.status}; only pending proposals can be decided."
        )
    row.status = ProposalStatus.APPROVED if approve else ProposalStatus.REJECTED
    row.decided_at = at or utcnow()
    row.decided_by = by
    ledger.audit(session, "proposal_decided", proposal_id=row.id, approved=approve, by=by)
    session.flush()
    return row


def handle_telegram_callback(ctx: AppContext, callback: dict[str, Any]) -> str:
    chat_id = str(callback.get("message", {}).get("chat", {}).get("id", ""))
    if not ctx.settings.telegram_chat_id or chat_id != str(ctx.settings.telegram_chat_id):
        return "Ignored: this chat is not allowed to approve trades."
    action, _, raw_id = str(callback.get("data", "")).partition(":")
    if action not in ("approve", "reject") or not raw_id.isdigit():
        return "Unknown action."
    with ctx.session() as session:
        try:
            row = decide_proposal(
                session, int(raw_id), action == "approve", by="telegram", label=ctx.label, at=ctx.now()
            )
        except (ProposalNotFoundError, InvalidTransitionError) as exc:
            return str(exc)
        verb = "Approved" if action == "approve" else "Rejected"
        return f"{verb} #{row.id}: {row.side} {row.qty} {row.symbol}"
