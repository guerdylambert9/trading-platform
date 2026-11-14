"""Message text for proposals and job results."""

from __future__ import annotations

from collections.abc import Sequence
from typing import TYPE_CHECKING

from trader.db import ProposalRow
from trader.models import ProposalStatus

if TYPE_CHECKING:
    from trader.services.context import AppContext


def proposal_line(row: ProposalRow) -> str:
    stop = f", stop {row.stop_price:.2f}" if row.stop_price else ""
    return f"#{row.id} {row.side.upper()} {row.qty} {row.symbol} @ {row.limit_price:.2f}{stop} ({row.kind})"


def notify_proposals(ctx: AppContext, rows: Sequence[ProposalRow]) -> None:
    pending = [r for r in rows if r.status == ProposalStatus.PENDING]
    approved = [r for r in rows if r.status == ProposalStatus.APPROVED]
    blocked = [r for r in rows if r.status == ProposalStatus.BLOCKED]
    if not rows:
        return
    head = f"[{ctx.settings.mode_label} {ctx.label}] Signals for {rows[0].as_of}"
    summary = f"{len(pending)} waiting for approval, {len(approved)} auto-approved, {len(blocked)} blocked."
    ctx.notify(f"{head}: {summary}")
    for row in pending:
        ai = f"\nAI: {row.ai_rating}" if row.ai_rating and row.ai_rating != "no_opinion" else ""
        ctx.notify(
            f"{proposal_line(row)}\n{row.reason}{ai}",
            buttons=[[("Approve", f"approve:{row.id}"), ("Reject", f"reject:{row.id}")]],
        )
    if blocked:
        lines = [
            f"{proposal_line(r)}: " + ", ".join(v.get("code", "?") for v in (r.violations or []))
            for r in blocked
        ]
        ctx.notify("Blocked by risk checks:\n" + "\n".join(lines))
