"""Holidays source — `holidays` package + `zoneinfo` DST markers.

Pure and fully offline: no network, no I/O. Produces contract agenda-items
(`start`/`all_day`/`title`/`kind`, with a date-only `start`) for a date window,
ready to merge with the Proton personal events into one sorted agenda (the
Phase-5 merge increment).

Three tiers (per the 2026-06-28 decision; the lesser tier is the full set —
user chose all 10):
  * federal US holidays -> kind="holiday"    (observed=False -> actual dates,
                                              no shifted "(observed)" ghost)
  * lesser/unofficial   -> kind="observance" (Valentine's, Halloween, ...)
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
    return (
        "Daylight Saving Time begins — clocks forward 1 h"
        if forward
        else "Daylight Saving Time ends — clocks back 1 h"
    )


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
        for d, title in _us(start, end, "unofficial").items()
        if start <= d <= end
    ]
    markers = [_item(d, title, "info") for d, title in _dst_markers(start, end, tz_name)]
    return sorted(
        federal + observances + markers,
        key=lambda i: (i["start"], i["kind"], i["title"]),
    )
