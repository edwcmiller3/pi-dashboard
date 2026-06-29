"""Holidays source — `holidays` package + `zoneinfo` DST markers.

Pure and fully offline: no network, no I/O. Produces contract agenda-items
(`start`/`all_day`/`title`/`kind`, with a date-only `start`) for a date window,
ready to merge with the Proton personal events into one sorted agenda (the
Phase-5 merge increment).

Three tiers (per the 2026-06-28 decision; the lesser tier is the full set —
user chose all 10):
  * federal US holidays -> kind="holiday"    (observed=False -> actual dates,
                                              no shifted "(observed)" ghost)
  * lesser/unofficial   -> kind="observance" (Valentine's, Halloween, ...),
                                              plus computed cultural extras the
                                              lib lacks (Black Friday, Mardi
                                              Gras, ... — rule-based, never
                                              hardcoded per year)
  * DST start/end        -> kind="info"       (from zoneinfo, not the holidays
                                              lib — DST is not a holiday)
"""

from __future__ import annotations

from datetime import date, datetime, time, timedelta
from typing import Any
from zoneinfo import ZoneInfo

import holidays

# The dashboard's display zone — US/Eastern, consistent with the US holiday set
# and the config lat/long default. A parameter so the DST scan stays testable.
_DISPLAY_TZ = "America/New_York"


def _years(start: date, end: date) -> range:
    """Calendar years the window touches (handles a year-boundary window)."""
    return range(start.year, end.year + 1)


def _us(start: date, end: date, category: str) -> dict[date, str]:
    """US holidays of one `holidays` category over the window's years, as actual
    dates (`observed=False` drops the shifted day-off duplicate at the source).

    Uses the `country_holidays` factory rather than `holidays.US` — the country
    classes are registered dynamically, so the factory is the statically-typed
    public entry point."""
    return holidays.country_holidays(
        "US", years=list(_years(start, end)), observed=False, categories=(category,)
    )


def _dst_title(forward: bool) -> str:
    """forward = spring-forward (offset increased, e.g. -5h -> -4h)."""
    return "Daylight Saving Time begins" if forward else "Daylight Saving Time ends"


def _dst_markers(start: date, end: date, tz_name: str) -> list[tuple[date, str]]:
    """Each UTC-offset change in [start, end] as (date, title). Pairs each day
    with the day before (via `zip(offsets, offsets[1:])`) and keeps the days the
    offset changed. The noon offset sidesteps the ambiguous 1–3am transition
    window, so a change is attributed to the calendar day it occurs on."""
    tz = ZoneInfo(tz_name)

    def offset(d: date) -> timedelta:
        off = datetime.combine(d, time(12), tzinfo=tz).utcoffset()
        assert off is not None  # an aware ZoneInfo datetime always has an offset
        return off

    # One day of lead-in so a transition landing exactly on `start` is detected.
    span = (end - start).days
    days = [start + timedelta(days=i) for i in range(-1, span + 1)]
    offsets = [(d, offset(d)) for d in days]
    return [
        (cur_d, _dst_title(cur_off > prev_off))
        for (_, prev_off), (cur_d, cur_off) in zip(offsets, offsets[1:])
        if cur_off != prev_off
    ]


# Cultural observances the `holidays` lib doesn't carry, as (month, day, title)
# rules — fixed-date, so no per-year dates ever get hardcoded.
_FIXED_EXTRAS = (
    (4, 1, "April Fools' Day"),
    (4, 22, "Earth Day"),
    (5, 5, "Cinco de Mayo"),
)


def _named(start: date, end: date, category: str, name: str) -> list[date]:
    """Dates of one specifically-named US holiday over the window's years. The
    anchor may itself fall outside [start, end] (e.g. Easter anchors Mardi Gras
    from a February window), so callers window the *derived* date, not this."""
    return [d for d, n in _us(start, end, category).items() if n == name]


def _extras(start: date, end: date) -> list[tuple[date, str]]:
    """Common cultural observances absent from the `holidays` lib, as (date,
    title). All rule-based — fixed month/day, or anchored on Thanksgiving /
    Easter that the lib already gives us — so nothing is hardcoded per year."""
    fixed = [
        (date(y, month, day), title)
        for y in _years(start, end)
        for month, day, title in _FIXED_EXTRAS
    ]
    thanksgiving = _named(start, end, "public", "Thanksgiving Day")
    easter = _named(start, end, "unofficial", "Easter Sunday")
    anchored = (
        [(d + timedelta(days=1), "Black Friday") for d in thanksgiving]
        + [(d + timedelta(days=4), "Cyber Monday") for d in thanksgiving]
        + [(d - timedelta(days=47), "Mardi Gras") for d in easter]
    )
    return fixed + anchored


def _item(d: date, title: str, kind: str) -> dict[str, Any]:
    """A contract agenda-item. Holidays/markers are always all-day, date-only."""
    return {"start": d.isoformat(), "all_day": True, "title": title, "kind": kind}


def get_holidays(
    start: date, end: date, tz_name: str = _DISPLAY_TZ
) -> list[dict[str, Any]]:
    """Federal holidays + lesser observances + DST markers within [start, end],
    as contract agenda-items sorted by date. Pure/offline — safe every tick."""
    federal = [
        _item(d, title, "holiday")
        for d, title in _us(start, end, "public").items()
        if start <= d <= end
    ]
    observances = [
        _item(d, title, "observance")
        for d, title in list(_us(start, end, "unofficial").items()) + _extras(start, end)
        if start <= d <= end
    ]
    markers = [_item(d, title, "info") for d, title in _dst_markers(start, end, tz_name)]
    return sorted(
        federal + observances + markers,
        key=lambda i: (i["start"], i["kind"], i["title"]),
    )
