"""FastAPI application entrypoint.

Phase 3 — the thin vertical slice: a background refresh loop fetches live
weather, normalizes it to the data contract, and caches the doc; `/api/data`
serves that doc to the polling frontend. Calendar is a stub block until Phase 5.

The refresh loop is deliberately "unkillable": a failing tick is caught and
logged so the loop survives (the cache keeps the last-good doc), the task is
held by a strong `app.state` ref so it isn't garbage-collected mid-flight, and
a done-callback logs loudly if it ever exits unexpectedly. This pattern is
load-bearing for the Phase-6 freshness hardening, established now with one source.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from app import cache
from app.sources.weather import get_weather

log = logging.getLogger("pi_dashboard.refresh")

_CACHE_KEY = "dashboard"
# Backend fetch cadence. Phase 6 makes this TTL-driven (base tick <= shortest TTL).
_REFRESH_INTERVAL_SECONDS = 900


async def _refresh_once() -> None:
    """Build the dashboard doc from the live sources and cache it."""
    weather = await get_weather()
    doc = {
        "generated_at": weather["fetched_at"],
        "weather": weather,
        # Phase 5 wires the live Proton feed + holidays here; until then the
        # calendar reads as stale (ok=False) with no events — honest, not blank.
        "calendar": {"ok": False, "fetched_at": None, "events": []},
    }
    cache.write(_CACHE_KEY, doc)


async def _refresh_loop() -> None:
    """The unkillable refresh cycle — a failing tick is logged, never fatal."""
    while True:
        try:
            await _refresh_once()
        except Exception:
            log.exception("refresh tick failed; keeping last-good cache")
        await asyncio.sleep(_REFRESH_INTERVAL_SECONDS)


def _loop_exited(task: asyncio.Future[None]) -> None:
    # Fires only on shutdown cancellation in normal operation; log loudly otherwise.
    if not task.cancelled():
        log.error("refresh loop exited unexpectedly: %r", task.exception())


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    task = asyncio.create_task(_refresh_loop())
    app.state.refresh_task = task  # strong ref so the loop isn't GC'd mid-flight
    task.add_done_callback(_loop_exited)
    try:
        yield
    finally:
        task.cancel()


app = FastAPI(title="pi-dashboard", version="0.1.0", lifespan=lifespan)


@app.get("/healthz")
def healthz() -> JSONResponse:
    """Liveness probe — also the thing the Phase-1 exit criterion hits."""
    return JSONResponse({"status": "ok"})


@app.get("/api/data")
def api_data() -> JSONResponse:
    """The normalized dashboard contract the frontend polls.

    503 until the first refresh tick warms the cache — the frontend degrades
    visibly (stale dots + "Data unavailable") on any non-200, never a blank panel.
    """
    doc = cache.read(_CACHE_KEY)
    if doc is None:
        return JSONResponse({"detail": "warming up"}, status_code=503)
    return JSONResponse(doc)


# Serve the static dashboard. html=True serves index.html at "/". Mounted last
# so /healthz and /api/* take precedence over the catch-all static mount.
_static_dir = Path(__file__).resolve().parent.parent / "static"
app.mount("/", StaticFiles(directory=_static_dir, html=True), name="static")
