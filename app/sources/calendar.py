"""Calendar source — Proton ICS (Full-view URL) merged with offline holidays.

Two layers, kept apart so the transform is pure and unit-testable (mirrors
`weather.py`):
  * `normalize_events(ics_text, start, end, tz)` — pure: raw ICS text -> the
    contract's personal agenda-items. Parses with `icalendar`, expands
    recurrences with `recurring-ical-events` over tz-aware `[start, end)` bounds
    (naive bounds raise — lib #26), honors EXDATE-on-master (confirmed 0.D1),
    and normalizes the DATE-vs-DATETIME split: all-day -> date-only `start`
    (`all_day=True`); timed -> ISO-with-offset `start` (`all_day=False`).
  * `get_calendar(now)` — impure: fetch the ICS (offloaded off the event loop),
    normalize, and MERGE with `holidays.get_holidays(window)` into one flat,
    sorted, windowed `events` list wrapped with `ok`/`fetched_at`.

`ok` tracks the Proton fetch ONLY. Holidays/observances/DST are offline and
always merge in regardless — so a Proton outage (or no URL configured) still
shows holidays, with the calendar honestly flagged stale. Per-source last-good
cache fallback is Phase 6.

The Proton URL is a SECRET bearer credential (embeds the decryption key inline)
and the feed is PII-bearing. The URL is NEVER logged — fetch/parse failures log
only the exception *type*, never the exception (whose message/traceback would
carry the URL). Event titles are untrusted PII; the frontend renders them via
`textContent`. See README "Secrets & data handling".
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

# Pooled session reused across refresh ticks (see app.http). Module-level: the
# refresh loop serializes fetches, so only one worker thread uses it at a time.
_SESSION: Final = build_session()

# The dashboard's display zone — matches the holidays source and the config
# lat/long default. A parameter throughout so the window/tz stays testable.
_DISPLAY_TZ: Final = "America/New_York"

# Agenda window: today + 4 future days, aligned with the 4-future-day forecast
# row. A short window (0.D1) — NOT a 180-day span that would expand a daily
# event into hundreds of rows.
_AGENDA_DAYS: Final = 5

_REQUEST_TIMEOUT_SECONDS: Final = 10

# Hard cap on the ICS body we'll buffer + parse. The 10s timeout bounds the
# network read, but `from_ical` parse time scales with input size, so an
# unbounded body could pin a worker thread. 5 MiB is generous for a personal
# Proton calendar (tens of thousands of events) while ruling out a pathological
# feed. Exceeding it soft-fails like any fetch error: last-good + holidays hold.
_MAX_ICS_BYTES: Final = 5 * 1024 * 1024


def _window(now: datetime, days: int = _AGENDA_DAYS) -> tuple[datetime, datetime]:
    """`[start-of-today, start-of-(today+days))` as tz-aware bounds in `now`'s
    zone — what `recurring_ical_events.between` consumes (aware required)."""
    start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    return start, start + timedelta(days=days)


def _iso(dt: date | datetime, tz: ZoneInfo) -> str:
    """Normalize an occurrence's DTSTART/DTEND to a contract ISO string.
    `datetime` subclasses `date`, so test datetime first: timed -> ISO-with-offset
    (the feed is tz-aware in the display zone per 0.D1; a naive datetime is
    localized as a defensive fallback); all-day DATE -> date-only `YYYY-MM-DD`."""
    if isinstance(dt, datetime):
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=tz)
        return dt.isoformat()
    return dt.isoformat()


def _agenda_item(occ: Any, tz: ZoneInfo) -> AgendaItem:
    """One expanded VEVENT occurrence -> a contract `personal` agenda-item.
    `occ` is `Any` — `recurring_ical_events` ships no types, so the library
    boundary is untyped; `_iso` re-establishes the date/datetime split.

    `start`/`end` are the half-open interval `[start, end)`. The library always
    synthesizes DTEND from DTSTART + duration (default: 1 day all-day, 0 timed),
    so it's read directly like DTSTART; ICS DTEND is exclusive, which is carried
    through verbatim (all-day single day -> `end == start + 1 day`)."""
    dtstart = occ["DTSTART"].dt
    # SUMMARY is untrusted PII; kept as a plain str, rendered via textContent.
    return {
        "start": _iso(dtstart, tz),
        "end": _iso(occ["DTEND"].dt, tz),
        "all_day": not isinstance(dtstart, datetime),
        "title": str(occ.get("SUMMARY") or ""),
        "kind": "personal",
    }


def normalize_events(
    ics_text: str, start: datetime, end: datetime, tz: ZoneInfo
) -> list[AgendaItem]:
    """Raw ICS text -> the window's personal agenda-items (pure). Recurrences
    are expanded over `[start, end)`; EXDATE-excluded occurrences are dropped by
    the library. Returned unsorted — `get_calendar` sorts the merged list.

    `between` returns every event OVERLAPPING the window, including a multi-day
    event that *began before* it — whose start is then out-of-window and would
    bucket into a day the agenda never renders. So filter to occurrences whose
    start lands in the window (matching the holidays source's date filter). Each
    item now carries `end` (the `[start, end)` upper bound), but the filter still
    drops pre-window starts — actually *rendering* an in-progress multi-day span
    across the days it covers is a separate Phase-9 polish concern."""
    cal = icalendar.Calendar.from_ical(ics_text)
    window_start = start.date().isoformat()  # date-prefix compare (ISO strings)
    items = (
        _agenda_item(occ, tz)
        for occ in recurring_ical_events.of(cal).between(start, end)
    )
    return [item for item in items if item["start"][:10] >= window_start]


def _read_capped(url: str) -> str:
    """Fetch the ICS text, refusing a body larger than `_MAX_ICS_BYTES`. Streamed
    so an oversized (or lying-Content-Length) feed is cut off mid-read rather than
    fully buffered. Raises ValueError on overflow — with only sizes in the message,
    never the secret URL. ICS is UTF-8 per spec; decode errors are replaced rather
    than raised so one bad byte can't drop the whole calendar."""
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
        return body.decode(resp.encoding or "utf-8", errors="replace")


def _fetch_personal(
    url: str, start: datetime, end: datetime, tz: ZoneInfo
) -> list[AgendaItem]:
    """Blocking fetch + parse (runs in a worker thread). Both the network call
    and the recurrence expansion are CPU/IO work kept off the event loop."""
    return normalize_events(_read_capped(url), start, end, tz)


def _last_good_personal(
    last_good: CalendarBlock | None, start: datetime, end: datetime
) -> list[AgendaItem]:
    """The personal events to fall back on when the Proton fetch fails — the
    `kind="personal"` items from the last-good doc, filtered to the CURRENT
    window. Holidays are excluded (they're recomputed fresh every tick, so
    carrying them would double them); out-of-window items are dropped so a
    prolonged outage doesn't surface stale events as the window slides forward."""
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
    """The contract's `calendar` block: personal + holiday items as one flat
    list sorted by (start, kind, title). Date-only all-day starts sort before
    same-day timed starts (shorter ISO string), so holidays/all-day lead a day;
    the `kind` tiebreak keeps holiday/observance/info ahead of personal."""
    events = sorted(
        personal + holiday, key=lambda i: (i["start"], i["kind"], i["title"])
    )
    return {"ok": ok, "fetched_at": fetched_at, "events": events}


async def get_calendar(
    now: datetime | None = None,
    tz_name: str = _DISPLAY_TZ,
    last_good: CalendarBlock | None = None,
) -> CalendarBlock:
    """The merged `calendar` block for the agenda window.

    Holidays/observances/DST (offline, never-fail) always merge in. The Proton
    fetch is best-effort: on any failure — or no URL configured — `ok=False`,
    `fetched_at=None`, and the last-good personal events (if any, in-window) are
    kept so a transient Proton blip doesn't wipe the user's meetings; holidays
    still show. Never raises for a Proton outage, so a calendar blip doesn't fail
    the whole refresh tick.
    """
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
        # NEVER log `exc` / use log.exception — the message+traceback carry the
        # secret URL. Log the type only.
        log.warning(
            "Proton calendar fetch/parse failed (%s); keeping last-good personal "
            "events + holidays",
            type(exc).__name__,
        )
        return _merge(ok=False, fetched_at=None, personal=fallback, holiday=holiday)

    fetched_at = datetime.now(tz).isoformat(timespec="seconds")
    return _merge(ok=True, fetched_at=fetched_at, personal=personal, holiday=holiday)
