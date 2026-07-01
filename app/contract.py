"""The typed data contract — the shapes the backend produces and the frontend
consumes (`/api/data`). One source of truth for every block that flows from a
source transform, through the refresh loop, into the JSON cache, and out to the
polling page.

TypedDicts, not Pydantic models, on purpose: each block IS a plain `dict` at
runtime, so it round-trips through the JSON cache (`json.dump`/`json.load`) with
no `.model_dump()`/re-parse step, and `cache.read` handing back a bare dict
needs no revalidation. The win over the old `dict[str, Any]` is that every
`block["ok"]` / `item["start"]` access is now statically checked under
`mypy --strict` (a typo or a producer/consumer drift fails the type-check
instead of surfacing at runtime) — without changing the runtime representation.

The *raw* external JSON (the Open-Meteo response, the deserialized cache doc)
stays `Any`: that's the genuine untyped boundary. Everything our own code
*constructs* downstream of a normalize step is typed here.
"""

from __future__ import annotations

from typing import Literal, NotRequired, TypedDict

# An agenda item's provenance. "personal" = a Proton event; the rest are the
# offline holidays source (federal holiday / lesser observance / DST marker).
Kind = Literal["personal", "holiday", "observance", "info"]


class AgendaItem(TypedDict):
    """One row of the merged agenda.

    `start`/`end` are a half-open interval `[start, end)` — an event occupies
    from `start` (inclusive) up to but not including `end`:
      * timed    -> ISO datetime-with-offset (see `calendar._iso`); `end` is the
                    exclusive end instant (`== start` for a zero-duration event).
      * all-day  -> date-only `YYYY-MM-DD`; `end` is the exclusive day AFTER the
                    last day covered (raw ICS DTEND), so a single-day all-day
                    event has `end == start + 1 day` and a span covers the dates
                    `[start, end)`.

    `end` is `NotRequired`: the offline holiday/observance/info items are
    single-day and omit it, and a last-good doc cached before `end` existed won't
    carry it — consumers must treat a missing `end` as a single-day/instant item.
    """

    start: str
    end: NotRequired[str]
    all_day: bool
    title: str
    kind: Kind


class SourceBlock(TypedDict):
    """Fields common to every source block. `ttl` and `attempted_at` are stamped
    by the refresh layer, not by the source fetch, so both are `NotRequired`:
      * `ttl` — the source's refresh cadence, added when the block is cached.
      * `attempted_at` — set ONLY on a failed tick that fell back to last-good;
        rate-limits retries so a down source isn't hammered (see `main._is_due`).
    """

    ok: bool
    fetched_at: str | None
    ttl: NotRequired[int]
    attempted_at: NotRequired[str]


class CurrentWeather(TypedDict):
    temp_f: int
    feels_like_f: int
    code: int
    text: str
    icon: str
    is_day: bool
    humidity_pct: int
    wind_mph: int
    precip_prob_pct: int
    high_f: int
    low_f: int
    sunrise: str
    sunset: str


class ForecastDay(TypedDict):
    date: str
    code: int
    text: str
    icon: str
    high_f: int
    low_f: int
    precip_prob_pct: int


class WeatherData(TypedDict):
    """The pure `normalize_weather` output — the weather payload without the
    `ok`/`fetched_at` envelope (`get_weather` wraps it into a `WeatherBlock`)."""

    current: CurrentWeather
    forecast: list[ForecastDay]


class WeatherBlock(SourceBlock):
    current: CurrentWeather
    forecast: list[ForecastDay]


class CalendarBlock(SourceBlock):
    events: list[AgendaItem]


class DashboardDoc(TypedDict):
    """The full document `/api/data` serves and the cache holds."""

    generated_at: str
    clock_synced: bool
    weather: WeatherBlock
    calendar: CalendarBlock
