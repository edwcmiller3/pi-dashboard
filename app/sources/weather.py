"""Weather source — Open-Meteo.

Two layers, kept apart so the transform is pure and unit-testable:
  * `normalize_weather(raw)` — pure: raw Open-Meteo JSON -> the contract's
    `weather` block (`current` + 4 future-day `forecast`). The frontend never
    sees raw WMO codes; `icon`/`text` are resolved here via `weather_codes`.
  * `get_weather()` — impure: the single Open-Meteo call, offloaded off the
    event loop via `asyncio.to_thread`, wrapped with `ok`/`fetched_at`.

Param set verified against the live API 2026-06-28:
one request, no extra dependency. `forecast_days=5` returns today + 4 future;
the cards use `daily[1:5]`, the hero uses `daily[0]`.
"""

from __future__ import annotations

import asyncio
import math
from datetime import datetime, timedelta, timezone
from typing import Any, Final

from app.config import settings
from app.contract import CurrentWeather, ForecastDay, WeatherBlock, WeatherData
from app.http import build_session
from app.sources.nws import Observation, fetch_observation
from app.weather_codes import describe, is_wet

_API_URL: Final = "https://api.open-meteo.com/v1/forecast"

# Pooled session reused across refresh ticks (see app.http). Module-level: the
# refresh loop serializes fetches, so only one worker thread uses it at a time.
_SESSION: Final = build_session()

# current.precipitation is requested but deliberately unmapped: the contract
# surfaces precip *probability* (from daily), not the current precip *amount*.
_PARAMS: Final[dict[str, str | int | float]] = {
    "current": (
        "temperature_2m,apparent_temperature,relative_humidity_2m,"
        "weather_code,is_day,wind_speed_10m,precipitation"
    ),
    "daily": (
        "weather_code,temperature_2m_max,temperature_2m_min,"
        "precipitation_probability_max,sunrise,sunset"
    ),
    "temperature_unit": "fahrenheit",
    "wind_speed_unit": "mph",
    "precipitation_unit": "inch",
    "timezone": "auto",
    "forecast_days": 5,
}

_REQUEST_TIMEOUT_SECONDS: Final = 10

# forecast_days=5 -> today (hero) + 4 future (cards). The normalize step indexes
# daily[0] and slices daily[1:5], so a shorter series can't build a full block.
_REQUIRED_DAILY_DAYS: Final = 5


def _tz(utc_offset_seconds: int) -> timezone:
    """The dashboard location's fixed UTC offset (per the API's
    `utc_offset_seconds`) — the single zone we stamp and emit every time in."""
    return timezone(timedelta(seconds=utc_offset_seconds))


def _with_offset(naive_local_iso: str, tz: timezone) -> str:
    """Attach the location's offset to a naive-local Open-Meteo time so it obeys
    the contract's "every time is ISO-local-with-offset" rule — uniform with
    `fetched_at`/events and correct for a consumer that does `new Date(...)`.
    `'2026-06-29T06:22'` -> `'2026-06-29T06:22:00-04:00'`."""
    return datetime.fromisoformat(naive_local_iso).replace(tzinfo=tz).isoformat()


def _round_half_up(value: float) -> int:
    """Round to nearest int with halves going UP (72.5 -> 73). Python's built-in
    `round` is banker's rounding (round-half-to-even: round(72.5) == 72), which
    surprises on a temperature readout — use this for every displayed number."""
    return math.floor(value + 0.5)


def _pct(value: Any) -> int:
    """precipitation_probability_max can be null in the feed -> treat as 0%."""
    return 0 if value is None else _round_half_up(value)


def _forecast_day(daily: dict[str, Any], i: int) -> ForecastDay:
    """One look-ahead card from `daily` index `i`. Cards always use day glyphs."""
    code = int(daily["weather_code"][i])
    cond = describe(code, is_day=True)
    return {
        "date": daily["time"][i],
        "code": code,
        "text": cond["text"],
        "icon": cond["icon"],
        "high_f": _round_half_up(daily["temperature_2m_max"][i]),
        "low_f": _round_half_up(daily["temperature_2m_min"][i]),
        "precip_prob_pct": _pct(daily["precipitation_probability_max"][i]),
        "precip_expected": is_wet(code),
    }


def _require(raw: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    """Validate the shape `normalize_weather` indexes into, turning a cryptic
    KeyError/IndexError on a malformed or truncated payload into a legible
    ValueError. All-or-nothing on purpose (per-field tolerance was rejected):
    a bad response raises and the refresh loop keeps the last-good doc rather
    than rendering a partial weather block."""
    try:
        cur = raw["current"]
        daily = raw["daily"]
    except KeyError as exc:
        raise ValueError(f"Open-Meteo response missing top-level {exc}") from exc
    days = len(daily.get("time", []))
    if days < _REQUIRED_DAILY_DAYS:
        raise ValueError(
            f"Open-Meteo daily series too short: got {days}, "
            f"need {_REQUIRED_DAILY_DAYS}"
        )
    # Open-Meteo returns null sunrise/sunset at polar latitudes (no rise/set on a
    # polar day/night). lat/lon is user-configurable, so guard the today[0] reads
    # `normalize_weather` does: a null here would otherwise be a cryptic TypeError
    # out of `_with_offset`. Raise the same legible ValueError -> the loop keeps
    # last-good (all-or-nothing, like the short-series guard above). A genuinely
    # polar deployment would then show "weather unavailable" rather than crash.
    for key in ("sunrise", "sunset"):
        series = daily.get(key) or []
        if not series or series[0] is None:
            raise ValueError(f"Open-Meteo daily.{key}[0] missing/null (polar?)")
    return cur, daily


def normalize_weather(raw: dict[str, Any]) -> WeatherData:
    """Raw Open-Meteo JSON -> the contract's `weather` payload (pure)."""
    cur, daily = _require(raw)
    tz = _tz(int(raw["utc_offset_seconds"]))
    is_day = bool(cur["is_day"])
    cond = describe(int(cur["weather_code"]), is_day)
    current: CurrentWeather = {
        "temp_f": _round_half_up(cur["temperature_2m"]),
        "feels_like_f": _round_half_up(cur["apparent_temperature"]),
        "code": int(cur["weather_code"]),
        "text": cond["text"],
        "icon": cond["icon"],
        "is_day": is_day,
        "humidity_pct": _round_half_up(cur["relative_humidity_2m"]),
        "wind_mph": _round_half_up(cur["wind_speed_10m"]),
        # hero precip% = TODAY's daily max (current block has no probability)
        "precip_prob_pct": _pct(daily["precipitation_probability_max"][0]),
        "high_f": _round_half_up(daily["temperature_2m_max"][0]),
        "low_f": _round_half_up(daily["temperature_2m_min"][0]),
        # Open-Meteo returns naive-local (timezone=auto); attach the offset so
        # these obey the contract's ISO-local-with-offset rule like every time.
        "sunrise": _with_offset(daily["sunrise"][0], tz),
        "sunset": _with_offset(daily["sunset"][0], tz),
    }
    # Cards = the 4 FUTURE days (daily[1:5]); today (daily[0]) feeds the hero.
    forecast = [_forecast_day(daily, i) for i in range(1, 5)]
    return {"current": current, "forecast": forecast}


# Discard an observation older than this rather than merge a confidently wrong
# "now". Stations report hourly (plus SPECI on weather changes), so 90 min =
# "missed more than one cycle". A code constant, not a setting — promote only if
# someone actually needs to tune it.
_MAX_OBS_AGE: Final = timedelta(minutes=90)


def _obs_or(value: float | None, fallback: int) -> int:
    """An observed number (rounded for display) or the model's value when the
    station didn't report that field — the per-field half of fail-soft."""
    return fallback if value is None else _round_half_up(value)


def merge_current(
    model: CurrentWeather, obs: Observation, now: datetime
) -> CurrentWeather:
    """Overlay a station observation onto the model's current conditions (pure).

    A measurement beats an estimate, per field: temp/humidity/wind and the
    condition come from the observation where present; each missing field keeps
    the model's value. Feels-like chains heatIndex -> windChill -> obs temp
    (NWS nulls the first two exactly when they don't apply) and never falls
    back to the model's apparent temperature — a model feels-like next to an
    obs temp reads incoherently. Forecast-only concepts (precip probability,
    high/low, sunrise/sunset) and the clock-derived `is_day` stay the model's.

    A stale observation (older than `_MAX_OBS_AGE` at `now`, which the caller
    supplies so this stays deterministic) is discarded entirely. Condition
    mapping is fail-soft: an unmappable `wmo_code=None` keeps the model's
    code/text/icon, so the overlay can only correct the condition, never
    coarsen it. Returns a new dict; never mutates `model`.
    """
    if now - obs.timestamp > _MAX_OBS_AGE:
        return {**model}
    feels_like = next(
        (v for v in (obs.heat_index_f, obs.wind_chill_f, obs.temp_f) if v is not None),
        None,
    )
    cond = describe(obs.wmo_code, model["is_day"]) if obs.wmo_code is not None else None
    return {
        **model,
        "temp_f": _obs_or(obs.temp_f, model["temp_f"]),
        "feels_like_f": _obs_or(feels_like, model["feels_like_f"]),
        "humidity_pct": _obs_or(obs.humidity_pct, model["humidity_pct"]),
        "wind_mph": _obs_or(obs.wind_mph, model["wind_mph"]),
        "code": model["code"] if obs.wmo_code is None else obs.wmo_code,
        "text": model["text"] if cond is None else cond["text"],
        "icon": model["icon"] if cond is None else cond["icon"],
    }


def _stamp(utc_offset_seconds: int) -> str:
    """Stamp "now" in the dashboard location's offset (per the API, not the Pi
    clock), as ISO with an explicit offset — so the frontend renders the right
    wall-clock and compares instants correctly."""
    return datetime.now(_tz(utc_offset_seconds)).isoformat(timespec="seconds")


def _fetch_raw() -> dict[str, Any]:
    """The blocking Open-Meteo call (runs in a worker thread)."""
    resp = _SESSION.get(
        _API_URL,
        params={
            **_PARAMS,
            "latitude": settings.weather_lat,
            "longitude": settings.weather_lon,
            # merged here (not in _PARAMS) so a per-test settings override is
            # seen — _PARAMS is a module Final built once at import. An empty
            # WEATHER_MODEL in .env still means the provider default.
            "models": settings.weather_model or "best_match",
        },
        timeout=_REQUEST_TIMEOUT_SECONDS,
    )
    resp.raise_for_status()
    data: dict[str, Any] = resp.json()
    return data


async def get_weather() -> WeatherBlock:
    """Fetch + normalize, wrapped with `ok`/`fetched_at` for the contract.

    The blocking `requests` call is offloaded so the event loop never stalls.
    Raises on fetch/parse failure — the refresh loop catches it and keeps the
    last-good cached doc.
    """
    raw = await asyncio.to_thread(_fetch_raw)
    data = normalize_weather(raw)
    # Opt-in NWS overlay: a real station measurement beats the model's estimate
    # for the hero's current conditions. fetch_observation returns None on ANY
    # failure, so a flaky api.weather.gov can never fail the tick.
    if settings.nws_station:
        obs = await fetch_observation(settings.nws_station)
        if obs is not None:
            data["current"] = merge_current(
                data["current"], obs, datetime.now(timezone.utc)
            )
    return {
        "ok": True,
        "fetched_at": _stamp(int(raw["utc_offset_seconds"])),
        "current": data["current"],
        "forecast": data["forecast"],
    }
