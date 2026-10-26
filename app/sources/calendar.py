"""Calendar source: Proton ICS merged with the offline holidays source.

`ok` tracks the Proton fetch only; holidays always merge in, so a Proton outage
(or no URL) still shows them with the calendar flagged stale.

The Proton URL is a secret bearer credential (it embeds the decryption key) and
the feed is PII. The URL is never logged - failures log only the exception
type, since its message/traceback would carry the URL. Event titles are
untrusted; the frontend renders them via `textContent`.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import date, datetime, timedelta
from typing import Any, Final
from zoneinfo import ZoneInfo

import icalendar
import recurring_ical_events

from app.config import settings
from app.contract import AgendaItem, CalendarBlock
from app.http import build_session
from app.sources.holidays import get_holidays

log = logging.getLogger("pi_dashboard.calendar")

_SESSION: Final = build_session()

# Matches the holidays source and the config lat/long default.
_DISPLAY_TZ: Final = "America/New_York"

# Today + 4 future days, aligned with the forecast row. Kept short: a long
# window would expand a daily event into hundreds of rows.
_AGENDA_DAYS: Final = 5

_REQUEST_TIMEOUT_SECONDS: Final = 10

# The timeout bounds the network read, but parse time scales with size, so an
# unbounded body could pin a worker thread. 5 MiB is generous for a personal
# calendar; exceeding it soft-fails like any fetch error.
_MAX_ICS_BYTES: Final = 5 * 1024 * 1024


def _window(now: datetime, days: int = _AGENDA_DAYS) -> tuple[datetime, datetime]:
    """`[start-of-today, start-of-(today+days))`, tz-aware: naive bounds raise
    in `recurring_ical_events` (recurring-ical-events#26)."""
    start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    return start, start + timedelta(days=days)


def _iso(dt: date | datetime, tz: ZoneInfo) -> str:
    """Timed -> ISO with offset (a naive datetime is localized defensively);
    all-day -> `YYYY-MM-DD`. `datetime` subclasses `date`, so test it first."""
    if isinstance(dt, datetime):
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=tz)
        return dt.isoformat()
    return dt.isoformat()


def _agenda_item(occ: Any, tz: ZoneInfo) -> AgendaItem:
    """`occ` is `Any` because `recurring_ical_events` ships no types. The library
    always synthesizes DTEND, so it's read directly; it's exclusive, matching
    the contract's half-open `[start, end)`."""
    dtstart = occ["DTSTART"].dt
    return {
        "start": _iso(dtstart, tz),
        "end": _iso(occ["DTEND"].dt, tz),
        "all_day": not isinstance(dtstart, datetime),
        "title": str(occ.get("SUMMARY") or ""),
        "kind": "personal",
    }


def _covered_days(
    start: date, end: date, window_lo: date, window_hi: date
) -> list[date]:
    """Days of `[start, end)` within `[window_lo, window_hi)`. An in-progress
    span clamps up to Today rather than vanishing under a past day the agenda
    never draws."""
    lo = max(start, window_lo)
    hi = min(end, window_hi)
    return [lo + timedelta(days=i) for i in range((hi - lo).days)]


def _day_item(item: AgendaItem, day: date) -> AgendaItem:
    """A single-day copy of `item` on `day`, so the frontend's group-by-`start`
    files it under that day."""
    return {
        "start": day.isoformat(),
        "end": (day + timedelta(days=1)).isoformat(),
        "all_day": True,
        "title": item["title"],
        "kind": item["kind"],
    }


def _emit(item: AgendaItem, window_lo: date, window_hi: date) -> list[AgendaItem]:
    """All-day -> one item per covered in-window day. Timed -> kept only if it
    starts in the window: timed multi-day spans aren't rendered, and a
    pre-window start would bucket under a day the agenda never draws."""
    if item["all_day"]:
        days = _covered_days(
            date.fromisoformat(item["start"]),
            date.fromisoformat(item["end"]),
            window_lo,
            window_hi,
        )
        return [_day_item(item, day) for day in days]
    return [item] if date.fromisoformat(item["start"][:10]) >= window_lo else []


def normalize_events(
    ics_text: str, start: datetime, end: datetime, tz: ZoneInfo
) -> list[AgendaItem]:
    """The window's personal items, recurrences expanded, unsorted. `between`
    also returns events that began before the window; `_emit` handles those."""
    cal = icalendar.Calendar.from_ical(ics_text)
    window_lo, window_hi = start.date(), end.date()
    occurrences = (
        _agenda_item(occ, tz)
        for occ in recurring_ical_events.of(cal).between(start, end)
    )
    return [
        emitted for occ in occurrences for emitted in _emit(occ, window_lo, window_hi)
    ]


def _read_capped(url: str) -> str:
    """Streamed, so an oversized (or lying-Content-Length) feed is cut off
    mid-read. Overflow errors carry only sizes, never the secret URL."""
    with _SESSION.get(url, timeout=_REQUEST_TIMEOUT_SECONDS, stream=True) as resp:
        resp.raise_for_status()
        declared = resp.headers.get("Content-Length")
        if (
            declared is not None
            and declared.isdigit()
            and int(declared) > _MAX_ICS_BYTES
        ):
            raise ValueError(
                f"ICS Content-Length {declared} exceeds cap {_MAX_ICS_BYTES}"
            )
        body = bytearray()
        for chunk in resp.iter_content(chunk_size=64 * 1024):
            body.extend(chunk)
            if len(body) > _MAX_ICS_BYTES:
                raise ValueError(f"ICS body exceeded cap {_MAX_ICS_BYTES} bytes")
        # UTF-8 per RFC 5545; `resp.encoding` is ignored because requests
        # defaults charset-less `text/*` to ISO-8859-1, mojibaking titles.
        # Replace, don't raise, so one bad byte can't drop the calendar.
        return body.decode("utf-8", errors="replace")


def _fetch_personal(
    url: str, start: datetime, end: datetime, tz: ZoneInfo
) -> list[AgendaItem]:
    return normalize_events(_read_capped(url), start, end, tz)


def _last_good_personal(
    last_good: CalendarBlock | None, start: datetime, end: datetime
) -> list[AgendaItem]:
    """Last-good personal items in the current window. Holidays are excluded
    (recomputed every tick, so carrying them would double them)."""
    if not last_good:
        return []
    lo = start.date().isoformat()
    hi = end.date().isoformat()
    return [
        e
        for e in last_good.get("events", [])
        if e.get("kind") == "personal" and lo <= str(e.get("start", ""))[:10] < hi
    ]


def _merge(
    ok: bool,
    fetched_at: str | None,
    personal: list[AgendaItem],
    holiday: list[AgendaItem],
) -> CalendarBlock:
    """Date-only starts sort before same-day timed ones (shorter string), so
    all-day items lead a day; the `kind` tiebreak puts personal last."""
    events = sorted(
        personal + holiday, key=lambda i: (i["start"], i["kind"], i["title"])
    )
    return {"ok": ok, "fetched_at": fetched_at, "events": events}


async def get_calendar(
    now: datetime | None = None,
    tz_name: str = _DISPLAY_TZ,
    last_good: CalendarBlock | None = None,
) -> CalendarBlock:
    """Never raises for a Proton failure: `ok=False` and last-good personal
    events are kept, so a blip doesn't wipe meetings or fail the tick."""
    tz = ZoneInfo(tz_name)
    now = now or datetime.now(tz)
    start, end = _window(now)
    # Inclusive end date for the offline source (window end is exclusive).
    holiday = get_holidays(start.date(), (end - timedelta(days=1)).date(), tz_name)
    fallback = _last_good_personal(last_good, start, end)

    if not settings.proton_ics_url:
        return _merge(ok=False, fetched_at=None, personal=fallback, holiday=holiday)

    try:
        personal = await asyncio.to_thread(
            _fetch_personal, settings.proton_ics_url, start, end, tz
        )
    except Exception as exc:
        # Never log `exc` or use log.exception: they carry the secret URL.
        log.warning(
            "Proton calendar fetch/parse failed (%s); keeping last-good personal "
            "events + holidays",
            type(exc).__name__,
        )
        return _merge(ok=False, fetched_at=None, personal=fallback, holiday=holiday)

    fetched_at = datetime.now(tz).isoformat(timespec="seconds")
    return _merge(ok=True, fetched_at=fetched_at, personal=personal, holiday=holiday)
