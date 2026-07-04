"""Calendar source — Proton ICS (Full-view URL) merged with offline holidays.

Two layers, kept apart so the transform is pure and unit-testable (mirrors
`weather.py`):
  * `normalize_events(ics_text, start, end, tz)` — pure: raw ICS text -> the
    contract's personal agenda-items. Parses with `icalendar`, expands
    recurrences with `recurring-ical-events` over tz-aware `[start, end)` bounds
    (naive bounds raise — lib #26), honors EXDATE-on-master (confirmed 0.D1),
    and normalizes the DATE-vs-DATETIME split: all-day -> date-only `start`
    (`all_day=True`); timed -> ISO-with-offset `start` (`all_day=False`). A
    multi-day all-day span is exploded into one single-day item per day it covers
    within the window (an in-progress span clamps to Today) so it renders on each
    day; timed multi-day spans are still start-day-only (deferred).
  * `get_calendar(now)` — impure: fetch the ICS (offloaded off the event loop),
    normalize, and MERGE with `holidays.get_holidays(window)` into one flat,
    sorted, windowed `events` list wrapped with `ok`/`fetched_at`.

`ok` tracks the Proton fetch ONLY. Holidays/observances/DST are offline and
always merge in regardless — so a Proton outage (or no URL configured) still
shows holidays, with the calendar honestly flagged stale.

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


def _covered_days(
    start: date, end: date, window_lo: date, window_hi: date
) -> list[date]:
    """The days a half-open all-day span `[start, end)` occupies within the
    half-open window `[window_lo, window_hi)` (pure — all `date`). Clamps BOTH
    ends to the window: an in-progress span that began before the window is
    clamped up to `window_lo` (Today), so it renders from Today forward instead
    of vanishing under a past day the agenda never draws; a span running past the
    window is clamped down to `window_hi`. No overlap -> `[]` (the range is
    negative)."""
    lo = max(start, window_lo)
    hi = min(end, window_hi)
    return [lo + timedelta(days=i) for i in range((hi - lo).days)]


def _day_item(item: AgendaItem, day: date) -> AgendaItem:
    """One covered day of an all-day span -> a single-day all-day item spanning
    `[day, day+1)` (the same half-open `end` rule a single-day all-day event
    already gets). Carries the source item's `title`/`kind`; only the dates
    change, so the frontend's group-by-`start` naturally files it under `day`."""
    return {
        "start": day.isoformat(),
        "end": (day + timedelta(days=1)).isoformat(),
        "all_day": True,
        "title": item["title"],
        "kind": item["kind"],
    }


def _emit(item: AgendaItem, window_lo: date, window_hi: date) -> list[AgendaItem]:
    """One normalized occurrence -> the agenda item(s) it contributes.

    * All-day -> one single-day all-day item per day it covers within the window
      (a multi-day span repeats across each day). `_covered_days` clamps an
      in-progress span to Today, so it renders from Today forward.
    * Timed -> the item itself when its start lands in the window, else dropped.
      A timed span that began before the window is dropped too: timed multi-day
      rendering is deferred, and emitting its real pre-window start would bucket
      it under a day the agenda never renders."""
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
    """Raw ICS text -> the window's personal agenda-items (pure). Recurrences
    are expanded over `[start, end)`; EXDATE-excluded occurrences are dropped by
    the library. Returned unsorted — `get_calendar` sorts the merged list.

    `between` returns every event OVERLAPPING the window, including a multi-day
    event that *began before* it. Each occurrence is routed through `_emit`,
    which turns an all-day span into one item per covered in-window day (clamping
    an in-progress span up to Today) and passes a timed event through iff its
    start is in-window (timed multi-day spans stay dropped — deferred). All-day
    multi-day *rendering* is what supersedes the earlier drop-not-clamp rule."""
    cal = icalendar.Calendar.from_ical(ics_text)
    window_lo, window_hi = start.date(), end.date()
    occurrences = (
        _agenda_item(occ, tz)
        for occ in recurring_ical_events.of(cal).between(start, end)
    )
    return [
        emitted
        for occ in occurrences
        for emitted in _emit(occ, window_lo, window_hi)
    ]


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
        # Decode UTF-8 unconditionally (RFC 5545 §3.1.4 mandates it for
        # iCalendar). `resp.encoding` is deliberately ignored: requests defaults
        # any `text/*` response without an explicit charset to ISO-8859-1, which
        # would mojibake non-ASCII titles in a charset-less feed.
        return body.decode("utf-8", errors="replace")


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
