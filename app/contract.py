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

The *raw* external JSON is the genuine untyped boundary: the Open-Meteo response
stays `Any` (validated structurally in `weather._require`), and the deserialized
cache doc arrives as `Any`. Its two source blocks are narrowed back into typed
`WeatherBlock`/`CalendarBlock` at the read boundary via `as_weather_block`/
`as_calendar_block`, so the refresh loop's last-good handling gets real block
types, not `Any` that merely looks typed. The doc *envelope* is read loosely on
purpose — a doc cached under an earlier schema may predate a top-level field
(e.g. `generated_at`), which `_refresh_once` must tolerate. Everything our own
code *constructs* downstream of a normalize step is typed here.
"""

from __future__ import annotations

from typing import Final, Literal, NotRequired, TypedDict

from pydantic import TypeAdapter, ValidationError

from app.weather_codes import WiIcon

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
    icon: WiIcon
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
    icon: WiIcon
    high_f: int
    low_f: int
    precip_prob_pct: int
    # Whether this day precipitates (`weather_codes.is_wet(code)`) — the frontend
    # shows the precip-chance line only when true, so dry days stay clean and the
    # raw WMO code never has to be interpreted client-side. `NotRequired` for the
    # same reason as `AgendaItem.end`: a last-good block cached before this field
    # existed won't carry it; consumers must treat a missing value as dry.
    precip_expected: NotRequired[bool]


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


_WEATHER_ADAPTER: Final = TypeAdapter(WeatherBlock)
_CALENDAR_ADAPTER: Final = TypeAdapter(CalendarBlock)


def as_weather_block(raw: object) -> WeatherBlock | None:
    """Narrow an untyped cache value into a typed `WeatherBlock`, or None if it
    doesn't match — absent (cold boot), corrupt, or missing a REQUIRED field.
    This is the boundary where the untyped cache payload is validated INTO the
    typed world, so `_refresh_once`'s last-good handling gets a real block, not
    `Any`. A TypedDict validates to a plain `dict`, so the runtime representation
    is unchanged; `NotRequired` fields (`ttl`/`attempted_at`) may be absent, so a
    block cached under an earlier schema still validates."""
    try:
        return _WEATHER_ADAPTER.validate_python(raw)
    except ValidationError:
        return None


def as_calendar_block(raw: object) -> CalendarBlock | None:
    """Narrow an untyped cache value into a typed `CalendarBlock`, or None if it
    doesn't match (see `as_weather_block`)."""
    try:
        return _CALENDAR_ADAPTER.validate_python(raw)
    except ValidationError:
        return None
