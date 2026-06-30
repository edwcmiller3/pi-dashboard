"""FastAPI application entrypoint.

A background refresh loop fetches live weather + the merged calendar (Proton
personal events + offline holidays/observances/DST), normalizes them to the data
contract, and caches the doc; `/api/data` serves that doc to the polling frontend.

The refresh loop is deliberately "unkillable": a failing tick is caught and
logged so the loop survives (the cache keeps the last-good doc), the task is
held by a strong `app.state` ref so it isn't garbage-collected mid-flight, and
a done-callback logs loudly if it ever exits unexpectedly. This pattern is
load-bearing for the Phase-6 freshness hardening, established now with one source.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from datetime import datetime, timedelta
from pathlib import Path
from typing import TypeVar, cast
from zoneinfo import ZoneInfo

from fastapi import FastAPI
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from app import cache
from app.config import settings
from app.contract import DashboardDoc, SourceBlock
from app.sources.calendar import get_calendar
from app.sources.weather import get_weather

log = logging.getLogger("pi_dashboard.refresh")

_CACHE_KEY = "dashboard"
# The dashboard's display zone — stamps generated_at independent of any source.
_DISPLAY_TZ = "America/New_York"

# After a failed tick, retry sooner than the full base cadence so a transient
# blip recovers in seconds; the delay doubles each consecutive failure and is
# capped at the base tick so a sustained outage settles to the normal cadence.
_BACKOFF_START_SECONDS = 30

# systemd-timesyncd creates this once the clock is NTP-synced. Module-level so
# tests can repoint it; the dashboard's live wall-clock is only trustworthy once
# this exists on a Pi without a hardware RTC.
_TIMESYNC_MARKER = Path("/run/systemd/timesync/synchronized")

# Each refresh source yields a contract block of its own shape (weather vs.
# calendar). `_refresh_source` is generic over that block type so the per-source
# last-good plumbing is shared yet stays strongly typed end to end.
B = TypeVar("B", bound=SourceBlock)


def _clock_synced() -> bool:
    """Whether the system clock is NTP-synced (so the live clock is honest).

    On a non-systemd host (the dev Mac) the timesyncd runtime dir is absent and
    we can't tell — assume synced rather than show a false "not synced" warning.
    On the Pi the runtime dir exists from boot and the marker file appears once
    `systemd-timesyncd` syncs; absent-but-runtime-present means not-yet-synced.
    """
    try:
        if not _TIMESYNC_MARKER.parent.is_dir():
            return True
        return _TIMESYNC_MARKER.exists()
    except OSError:
        return True


def _iso_age(iso: str | None, now: datetime) -> float | None:
    """Seconds between an ISO stamp and `now`, or None if absent/unparseable."""
    if not isinstance(iso, str):
        return None
    try:
        return (now - datetime.fromisoformat(iso)).total_seconds()
    except ValueError:
        return None


def _is_due(
    block: SourceBlock | None,
    ttl: int,
    now: datetime,
    force: bool,
    *,
    retry_floor: int,
) -> bool:
    """Whether a source should be refetched this tick.

    Fresh-and-ok: due once the block has aged past its TTL. Forced or no prior:
    always due. Previously FAILED (ok=False): due once `retry_floor` seconds
    have passed since the last ATTEMPT — crucially NOT every tick. That floor is
    what stops a down source being hammered while the loop is in fast backoff:
    weather passes a small floor (retry in step with the backoff), the calendar
    passes its full TTL, so a Proton outage is retried gently even when a
    simultaneous weather outage (e.g. the whole network dropped) has the loop
    ticking every 30s."""
    if force or block is None:
        return True
    if not block.get("ok"):
        # `attempted_at` is stamped on every failed tick; fall back to the last
        # success stamp for a block that failed before that field was written.
        last = block.get("attempted_at") or block.get("fetched_at")
        age = _iso_age(last, now)
        return age is None or age >= retry_floor
    age = _iso_age(block.get("fetched_at"), now)
    return age is None or age >= ttl


def _backoff_delay(failures: int, base: int) -> int:
    """Post-failure retry delay: 30, 60, 120, … doubling per consecutive
    failure, capped at the base tick (`failures` is >= 1)."""
    return min(base, _BACKOFF_START_SECONDS << (failures - 1))


def _seconds_to_next_local_midnight(now: datetime) -> float:
    """Seconds from `now` until the next local midnight (00:00 in `now`'s zone).
    The loop clamps its sleep to this so a tick lands at the day boundary."""
    midnight = (now + timedelta(days=1)).replace(
        hour=0, minute=0, second=0, microsecond=0
    )
    return (midnight - now).total_seconds()


def _date_rolled(prev_iso: str | None, now: datetime) -> bool:
    """Whether `prev_iso` (a prior doc's `generated_at`) falls on a different
    local calendar day than `now` — i.e. the agenda window must roll even if every
    source is still within its TTL. Absent/unparseable -> False (cold boot or a
    corrupt cache: every source is due anyway, so forcing adds nothing)."""
    if not isinstance(prev_iso, str):
        return False
    try:
        return datetime.fromisoformat(prev_iso).date() != now.date()
    except ValueError:
        return False


async def _refresh_source(
    fetch: Callable[[], Awaitable[B]],
    prior: B | None,
    ttl: int,
    now: datetime,
    *,
    force: bool,
    retry_floor: int,
    name: str,
) -> tuple[B, bool]:
    """Refresh one source if due, returning (block, failed). `failed` is True
    only when a fetch was ATTEMPTED and fell back to last-good (drives backoff);
    a skipped-because-fresh source isn't a failure. On a cold-boot fetch failure
    with no last-good there's nothing to show, so the error propagates (the loop
    catches it; the route stays 503)."""
    if prior is not None and not _is_due(prior, ttl, now, force, retry_floor=retry_floor):
        return prior, False  # still fresh — reuse as-is, nothing attempted
    try:
        block = await fetch()
    except Exception:
        log.exception("%s refresh failed", name)
        if prior is None:
            raise
        # Keep last-good DATA, flag it stale, and stamp the attempt so `_is_due`
        # rate-limits the next retry. cast: {**TypedDict} widens to a plain dict,
        # but the keys are unchanged so the result is still a `B`.
        stale = {
            **prior,
            "ok": False,
            "ttl": ttl,
            "attempted_at": now.isoformat(timespec="seconds"),
        }
        return cast(B, stale), True
    return cast(B, {**block, "ttl": ttl}), False  # fresh fetch — not a failure


async def _refresh_once(force: bool = False, *, now: datetime | None = None) -> bool:
    """Build the dashboard doc from the (due) live sources and cache it.

    Each source is refreshed independently with per-source last-good fallback,
    so a weather blip can't wipe a good calendar refresh (or vice versa).
    Returns True for a healthy tick, False if any attempted source fell back to
    last-good (the loop uses this to back off and retry sooner).

    NOTE: the calendar soft-fails IN-BAND — `get_calendar` never raises (holidays
    must always show), so a Proton outage returns an `ok=False` block, not an
    exception, and the tick still reports healthy. Weather alone drives the loop
    backoff; the calendar's retry cadence on a Proton outage is governed entirely
    by its `retry_floor` below, so Proton is never hammered (see `_is_due`).

    The cache read/write are offloaded to a thread: they `fsync` (blocking), and
    this runs on the event loop, so — like the source fetches — they must not
    stall it."""
    now = now or datetime.now(ZoneInfo(_DISPLAY_TZ))
    prior_doc = await asyncio.to_thread(cache.read, _CACHE_KEY)
    prior = prior_doc if isinstance(prior_doc, dict) else {}

    # A local-day rollover (midnight) makes the cached agenda window stale even
    # when every source is within its TTL: today's column, and any holiday/event
    # entering the [today, +5d) window, only roll when the sources actually
    # refetch and recompute `now`. So force a full refresh when the cached doc was
    # built on an earlier day. `_refresh_loop` wakes at midnight so this fires
    # promptly rather than up to a full base interval late.
    force = force or _date_rolled(prior.get("generated_at"), now)

    weather, w_failed = await _refresh_source(
        get_weather,
        prior.get("weather"),
        settings.weather_ttl_seconds,
        now,
        force=force,
        retry_floor=_BACKOFF_START_SECONDS,  # hard source: retry in step w/ backoff
        name="weather",
    )
    calendar, c_failed = await _refresh_source(
        lambda: get_calendar(now=now, last_good=prior.get("calendar")),
        prior.get("calendar"),
        settings.calendar_ttl_seconds,
        now,
        force=force,
        retry_floor=settings.calendar_ttl_seconds,  # soft source: retry gently
        name="calendar",
    )

    doc: DashboardDoc = {
        # generated_at = when THIS doc was assembled — a source-independent clock
        # in the display zone, since weather/calendar fetch times diverge.
        "generated_at": now.isoformat(timespec="seconds"),
        "clock_synced": _clock_synced(),
        "weather": weather,
        "calendar": calendar,
    }
    await asyncio.to_thread(cache.write, _CACHE_KEY, doc)
    return not (w_failed or c_failed)


# Serializes the background loop and POST /refresh so a manual refresh can't
# race a scheduled tick into a double-fetch or interleaved cache write.
_refresh_lock = asyncio.Lock()


async def _refresh_loop() -> None:
    """The unkillable refresh cycle — a failing tick is logged, never fatal.
    Base cadence = the shortest source TTL; a failed tick backs off and retries
    sooner so transient blips clear without waiting the full interval. The sleep
    is also clamped to the next local midnight so a tick lands at 00:00 and the
    agenda window rolls on time (see `_refresh_once`), not a full interval late."""
    failures = 0
    while True:
        now = datetime.now(ZoneInfo(_DISPLAY_TZ))
        base = min(settings.weather_ttl_seconds, settings.calendar_ttl_seconds)
        try:
            async with _refresh_lock:
                healthy = await _refresh_once(now=now)
        except Exception:
            log.exception("refresh tick failed; keeping last-good cache")
            healthy = False
        if healthy:
            failures = 0
            delay = float(base)
        else:
            failures += 1
            delay = float(_backoff_delay(failures, base))
        # Wake just after the next local midnight if that's sooner than the normal
        # delay, so the day-rollover refresh fires promptly at the day boundary.
        delay = min(delay, _seconds_to_next_local_midnight(now) + 1.0)
        await asyncio.sleep(delay)


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


@app.post("/refresh")
async def refresh() -> JSONResponse:
    """Force an immediate refresh of every source (the status row's manual
    refresh control). Serialized with the background loop via `_refresh_lock`
    so it can't race a scheduled tick."""
    async with _refresh_lock:
        try:
            await _refresh_once(force=True)
        except Exception:
            log.exception("manual refresh failed")
            return JSONResponse({"detail": "refresh failed"}, status_code=502)
    return JSONResponse({"status": "refreshed"})


# Serve the static dashboard. html=True serves index.html at "/". Mounted last
# so /healthz and /api/* take precedence over the catch-all static mount.
_static_dir = Path(__file__).resolve().parent.parent / "static"
app.mount("/", StaticFiles(directory=_static_dir, html=True), name="static")
