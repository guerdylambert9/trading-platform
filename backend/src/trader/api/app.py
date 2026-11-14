"""FastAPI app: the dashboard API, plus the built dashboard itself when frontend/dist exists."""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from trader import __version__
from trader.api.routes import build_router
from trader.notify.telegram import TelegramNotifier, TelegramPoller
from trader.services.context import AppContext, build_context

log = logging.getLogger(__name__)


def create_app(ctx: AppContext | None = None, start_background: bool | None = None) -> FastAPI:
    ctx = ctx or build_context()
    background = ctx.settings.enable_scheduler if start_background is None else start_background

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        scheduler = None
        poller = None
        if background:
            from trader.scheduler import start_scheduler

            scheduler = start_scheduler(ctx)
            ctx.scheduler_running = True
            if isinstance(ctx.notifier, TelegramNotifier):
                poller = TelegramPoller(ctx, ctx.notifier)
                poller.start()
        yield
        if scheduler is not None:
            scheduler.shutdown(wait=False)
            ctx.scheduler_running = False
        if poller is not None:
            poller.stop()

    app = FastAPI(title="Trading Platform API", version=__version__, lifespan=lifespan)
    app.state.ctx = ctx
    app.add_middleware(
        CORSMiddleware,
        allow_origins=ctx.settings.cors_origin_list,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.include_router(build_router(ctx), prefix="/api")

    dist = Path(ctx.settings.frontend_dist)
    if (dist / "index.html").exists():
        app.mount("/", StaticFiles(directory=dist, html=True), name="dashboard")
    else:
        log.info("No built dashboard at %s; run `npm run build` in frontend/ to serve it here.", dist)
    return app
