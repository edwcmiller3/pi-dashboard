"""Offline holidays source: all-day agenda items for a date window.

* federal US holidays -> kind="holiday"
* unofficial observances, plus rule-based extras the lib lacks (Black
  Friday, Mardi Gras, ...) -> kind="observance"
* DST start/end, from zoneinfo -> kind="info"
"""

from __future__ import annotations

from datetime import date, datetime, time, timedelta
from typing import Final
from zoneinfo import ZoneInfo

import holidays

from app.contract import AgendaItem, Kind

# Matches the US holiday set and the config lat/long default.
_DISPLAY_TZ: Final = "America/New_York"


def _years(start: date, end: date) -> range:
    return range(start.year, end.year + 1)


def _us(start: date, end: date, category: str) -> dict[date, str]:
    """`observed=False` drops the shifted "(observed)" day-off duplicate. The
    factory, not `holidays.US`, because country classes are registered
    dynamically and only the factory is statically typed."""
    return holidays.country_holidays(
        "US", years=list(_years(start, end)), observed=False, categories=(category,)
    )


def _dst_title(forward: bool) -> str:
    return "Daylight Saving Time begins" if forward else "Daylight Saving Time ends"


def _dst_markers(start: date, end: date, tz_name: str) -> list[tuple[date, str]]:
    """Each UTC-offset change in [start, end] as (date, title). Sampling at noon
    sidesteps the ambiguous 1-3am transition window."""
    tz = ZoneInfo(tz_name)

    def offset(d: date) -> timedelta:
        off = datetime.combine(d, time(12), tzinfo=tz).utcoffset()
        if off is None:  # aware ZoneInfo always has an offset; survives `-O`
            raise RuntimeError(f"no UTC offset for {d} in {tz_name}")
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


# Observances the `holidays` lib doesn't carry, as (month, day, title).
_FIXED_EXTRAS: Final = (
    (3, 14, "Pi Day"),
    (4, 1, "April Fools' Day"),
    (4, 22, "Earth Day"),
    (5, 1, "May Day"),
    (5, 5, "Cinco de Mayo"),
    (9, 19, "Talk Like a Pirate Day"),
)


def _named(start: date, end: date, category: str, name: str) -> list[date]:
    """Unwindowed: the anchor may fall outside [start, end] (Easter anchors Mardi
    Gras from a February window), so callers window the derived date."""
    return [d for d, n in _us(start, end, category).items() if n == name]


def _election_day(year: int) -> date:
    """The Tuesday after the first Monday of November."""
    nov1 = date(year, 11, 1)
    first_monday = nov1 + timedelta(days=(-nov1.weekday()) % 7)
    return first_monday + timedelta(days=1)


def _extras(start: date, end: date) -> list[tuple[date, str]]:
    """Rule-based observances absent from the lib, as (date, title); nothing is
    hardcoded per year. Election Day covers every even year, including midterms
    the lib omits."""
    fixed = [
        (date(y, month, day), title)
        for y in _years(start, end)
        for month, day, title in _FIXED_EXTRAS
    ]
    election = [
        (_election_day(y), "Election Day") for y in _years(start, end) if y % 2 == 0
    ]
    thanksgiving = _named(start, end, "public", "Thanksgiving Day")
    easter = _named(start, end, "unofficial", "Easter Sunday")
    anchored = (
        [(d + timedelta(days=1), "Black Friday") for d in thanksgiving]
        + [(d + timedelta(days=4), "Cyber Monday") for d in thanksgiving]
        + [(d - timedelta(days=47), "Mardi Gras") for d in easter]
    )
    return fixed + election + anchored


def _unofficial(start: date, end: date) -> list[tuple[date, str]]:
    """Minus the lib's presidential-year-only Election Day; `_extras` owns it."""
    return [
        (d, n) for d, n in _us(start, end, "unofficial").items() if n != "Election Day"
    ]


def _item(d: date, title: str, kind: Kind) -> AgendaItem:
    return {"start": d.isoformat(), "all_day": True, "title": title, "kind": kind}


def get_holidays(
    start: date, end: date, tz_name: str = _DISPLAY_TZ
) -> list[AgendaItem]:
    """Holidays, observances and DST markers within [start, end], sorted by date."""
    federal = [
        _item(d, title, "holiday")
        for d, title in _us(start, end, "public").items()
        if start <= d <= end
    ]
    observances = [
        _item(d, title, "observance")
        for d, title in _unofficial(start, end) + _extras(start, end)
        if start <= d <= end
    ]
    markers = [
        _item(d, title, "info") for d, title in _dst_markers(start, end, tz_name)
    ]
    return sorted(
        federal + observances + markers,
        key=lambda i: (i["start"], i["kind"], i["title"]),
    )
