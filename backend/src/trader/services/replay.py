"""Replay the live jobs day by day against the fake broker.

It drives the real pipeline, submission and reconciliation with a simulated clock, so it
doubles as the demo and as an end-to-end test of the live path. Fills use each day's close.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, date, datetime, time
from typing import TYPE_CHECKING

from trader.broker.fake import FakeBroker
from trader.notify.telegram import LogNotifier
from trader.services.approvals import decide_proposal
from trader.services.execution import submit_approved
from trader.services.pipeline import run_nightly
from trader.services.reconcile import reconcile
from trader.utils import NY, is_number

if TYPE_CHECKING:
    from trader.services.context import AppContext


@dataclass
class ReplayResult:
    days: int
    start: date | None
    end: date | None
    submitted: int
    stops_filled: int
    final_equity: float


class _Clock:
    def __init__(self) -> None:
        self.moment = datetime.now(UTC)

    def set(self, day: date, hour: int, minute: int) -> None:
        self.moment = datetime.combine(day, time(hour, minute), tzinfo=NY).astimezone(UTC)

    def __call__(self) -> datetime:
        return self.moment


def replay(
    ctx: AppContext, start: date, end: date, approve_all: bool = True, leave_last_pending: bool = False
) -> ReplayResult:
    """Run the live jobs over [start, end]. With approve_all, every proposal is approved as you
    would in the dashboard; leave_last_pending keeps the final day's proposals for you to decide."""
    if not isinstance(ctx.broker, FakeBroker):
        raise ValueError("Replays only run against the fake broker (BROKER=fake).")
    settings = ctx.settings
    broker = ctx.broker
    symbols = list(dict.fromkeys([*settings.universe_list, settings.benchmark_symbol]))
    closes = ctx.bars.get_closes(symbols, start, end)
    days = [ts for ts in closes.index if start <= ts.date() <= end]

    clock = _Clock()
    saved = (ctx.now_fn, ctx.notifier, broker.now_fn, broker.always_open)
    ctx.now_fn, ctx.notifier = clock, LogNotifier()
    broker.now_fn, broker.always_open = clock, False
    submitted = stops = 0
    try:
        for number, ts in enumerate(days, start=1):
            day = ts.date()
            is_last = number == len(days)
            row = closes.loc[ts]
            broker.set_prices({s: float(row[s]) for s in symbols if is_number(row[s])})

            clock.set(day, 9, 50)
            submitted += len(submit_approved(ctx).submitted)
            stops += len(broker.trigger_stops())

            clock.set(day, 16, 30)
            reconcile(ctx)

            clock.set(day, 17, 15)
            result = run_nightly(ctx, as_of=day)
            if approve_all and result.proposal_ids and not (leave_last_pending and is_last):
                with ctx.session() as session:
                    for proposal_id in result.proposal_ids:
                        try:
                            decide_proposal(
                                session, proposal_id, True, by="replay", label=ctx.label, at=ctx.now()
                            )
                        except ValueError:
                            continue  # blocked ones stay blocked
            if not is_last:  # like Alpaca, today's P&L is measured from yesterday's close
                broker.end_of_day()
    finally:
        ctx.now_fn, ctx.notifier, broker.now_fn, broker.always_open = saved

    return ReplayResult(
        days=len(days),
        start=days[0].date() if days else None,
        end=days[-1].date() if days else None,
        submitted=submitted,
        stops_filled=stops,
        final_equity=broker.get_account().equity,
    )
