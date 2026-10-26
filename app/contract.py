"""The typed data contract served at `/api/data` and held in the cache.

TypedDicts rather than Pydantic models so each block stays a plain `dict` that
round-trips through the JSON cache unchanged, while access is still checked by
mypy. Cached source blocks are narrowed back to typed blocks via
`as_weather_block` / `as_calendar_block`; the doc envelope is read loosely
because a doc cached under an earlier schema may lack a top-level field.
"""

from __future__ import annotations

from typing import Final, Literal, NotRequired, TypedDict

from pydantic import TypeAdapter, ValidationError

from app.weather_codes import IconToken

# "personal" = a Proton event; the rest come from the offline holidays source
# (federal holiday / lesser observance / DST marker).
Kind = Literal["personal", "holiday", "observance", "info"]


class AgendaItem(TypedDict):
    """One row of the merged agenda; `[start, end)` is half-open.

    Timed items are ISO datetimes with offset (`end == start` for a zero-duration
    event). All-day items are `YYYY-MM-DD` with `end` the day after the last day
    covered (raw ICS DTEND). A missing `end` (offline items, older cached docs)
    means a single-day/instant item.
    """

    start: str
    end: NotRequired[str]
    all_day: bool
    title: str
    kind: Kind


class SourceBlock(TypedDict):
    """`ttl` and `attempted_at` are stamped by the refresh layer, not the fetch.
    `attempted_at` is set only on a failed tick that fell back to last-good, to
    rate-limit retries of a down source (see `main._is_due`)."""

    ok: bool
    fetched_at: str | None
    ttl: NotRequired[int]
    attempted_at: NotRequired[str]


class CurrentWeather(TypedDict):
    temp_f: int
    feels_like_f: int
    code: int
    text: str
    icon: IconToken
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
    icon: IconToken
    high_f: int
    low_f: int
    precip_prob_pct: int
    # `weather_codes.is_wet(code)`, so the frontend never interprets WMO codes.
    # Older cached blocks lack it; treat missing as dry.
    precip_expected: NotRequired[bool]


class WeatherData(TypedDict):
    """`normalize_weather` output, before `get_weather` adds the envelope."""

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
    """Validate an untyped cache value as a `WeatherBlock` (still a plain dict),
    or None if absent, corrupt, or missing a required field."""
    try:
        return _WEATHER_ADAPTER.validate_python(raw)
    except ValidationError:
        return None


def as_calendar_block(raw: object) -> CalendarBlock | None:
    """See `as_weather_block`."""
    try:
        return _CALENDAR_ADAPTER.validate_python(raw)
    except ValidationError:
        return None
