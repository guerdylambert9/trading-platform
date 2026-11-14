"""Background schedule (New York time, weekdays):

09:50  submit approved orders (after the first 15 minutes)
16:30  reconcile with the broker, record equity, cancel unfilled entries
17:15  nightly pipeline: signals, risk checks, proposals for your approval
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from typing import TYPE_CHECKING, Any

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger

from trader import ledger

if TYPE_CHECKING:
    from trader.services.context import AppContext

log = logging.getLogger(__name__)

SCHEDULE = {
    "submit": (9, 50),
    "reconcile": (16, 30),
    "nightly": (17, 15),
}


def guarded(ctx: AppContext, name: str, job: Callable[[], Any]) -> Callable[[], None]:
    def run() -> None:
        try:
            result = job()
            log.info("Job %s finished: %s", name, result)
        except Exception as exc:
            log.exception("Job %s failed", name)
            try:
                with ctx.session() as session:
                    ledger.audit(session, "job_failed", job=name, error=str(exc))
            finally:
                ctx.notify(f"[{ctx.settings.mode_label} {ctx.label}] Job '{name}' failed: {exc}")

    return run


def start_scheduler(ctx: AppContext) -> BackgroundScheduler:
    from trader.services.execution import submit_approved
    from trader.services.pipeline import run_nightly
    from trader.services.reconcile import reconcile

    jobs: dict[str, Callable[[], Any]] = {
        "submit": lambda: submit_approved(ctx),
        "reconcile": lambda: reconcile(ctx),
        "nightly": lambda: run_nightly(ctx),
    }
    scheduler = BackgroundScheduler(timezone=ctx.tz)
    for name, (hour, minute) in SCHEDULE.items():
        scheduler.add_job(
            guarded(ctx, name, jobs[name]),
            CronTrigger(day_of_week="mon-fri", hour=hour, minute=minute, timezone=ctx.tz),
            id=name,
            replace_existing=True,
            coalesce=True,
            misfire_grace_time=1800,
        )
    scheduler.start()
    log.info("Scheduler started: %s", ", ".join(f"{n} {h:02d}:{m:02d}" for n, (h, m) in SCHEDULE.items()))
    return scheduler
