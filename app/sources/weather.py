"""Open-Meteo weather source: a pure `normalize_weather` transform and the
impure `get_weather` fetch (plus the optional NWS overlay)."""

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

# today (hero, daily[0]) + 4 future days (cards, daily[1:5]).
_REQUIRED_DAILY_DAYS: Final = 5


def _tz(utc_offset_seconds: int) -> timezone:
    return timezone(timedelta(seconds=utc_offset_seconds))


def _with_offset(naive_local_iso: str, tz: timezone) -> str:
    """Open-Meteo times are naive local; the contract wants every time with an
    offset. `'2026-06-29T06:22'` -> `'2026-06-29T06:22:00-04:00'`."""
    return datetime.fromisoformat(naive_local_iso).replace(tzinfo=tz).isoformat()


def _round_half_up(value: float) -> int:
    """Use for every displayed number: built-in `round` is banker's rounding
    (round(72.5) == 72), which surprises on a temperature readout."""
    return math.floor(value + 0.5)


def _pct(value: Any) -> int:
    """The feed's probability can be null; treat as 0%."""
    return 0 if value is None else _round_half_up(value)


def _forecast_day(daily: dict[str, Any], i: int) -> ForecastDay:
    """Cards always use day glyphs."""
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
    """Turn a malformed payload into a legible ValueError. All-or-nothing on
    purpose: the refresh loop keeps last-good rather than render a partial
    block."""
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
    # Open-Meteo returns null sunrise/sunset at polar latitudes, which would
    # otherwise be a cryptic TypeError out of `_with_offset`.
    for key in ("sunrise", "sunset"):
        series = daily.get(key) or []
        if not series or series[0] is None:
            raise ValueError(f"Open-Meteo daily.{key}[0] missing/null (polar?)")
    return cur, daily


def _clamp_high_low(current: CurrentWeather) -> CurrentWeather:
    """Widen today's H/L to include the current temp: they come from different
    products (observation vs. model, or Open-Meteo current vs. daily), and the
    hero must never show now outside H/L."""
    return {
        **current,
        "high_f": max(current["high_f"], current["temp_f"]),
        "low_f": min(current["low_f"], current["temp_f"]),
    }


def normalize_weather(raw: dict[str, Any]) -> WeatherData:
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
        # The current block has no probability; use today's daily max.
        "precip_prob_pct": _pct(daily["precipitation_probability_max"][0]),
        "high_f": _round_half_up(daily["temperature_2m_max"][0]),
        "low_f": _round_half_up(daily["temperature_2m_min"][0]),
        "sunrise": _with_offset(daily["sunrise"][0], tz),
        "sunset": _with_offset(daily["sunset"][0], tz),
    }
    forecast = [_forecast_day(daily, i) for i in range(1, 5)]
    return {"current": _clamp_high_low(current), "forecast": forecast}


# Stations report hourly (plus SPECI on changes), so 90 min = missed more than
# one cycle; older than that is discarded rather than shown as a wrong "now".
_MAX_OBS_AGE: Final = timedelta(minutes=90)


def _obs_or(value: float | None, fallback: int) -> int:
    return fallback if value is None else _round_half_up(value)


def merge_current(
    model: CurrentWeather, obs: Observation, now: datetime
) -> CurrentWeather:
    """Overlay an observation onto the model's current conditions, per field;
    a missing field keeps the model's value and a stale observation is ignored.

    Feels-like chains heatIndex -> windChill -> obs temp (NWS nulls the first two
    when they don't apply) and never falls back to the model's, which would read
    incoherently beside an observed temp. Forecast-only fields and `is_day` stay
    the model's.
    """
    if now - obs.timestamp > _MAX_OBS_AGE:
        return {**model}
    feels_like = next(
        (v for v in (obs.heat_index_f, obs.wind_chill_f, obs.temp_f) if v is not None),
        None,
    )
    cond = describe(obs.wmo_code, model["is_day"]) if obs.wmo_code is not None else None
    return _clamp_high_low(
        {
            **model,
            "temp_f": _obs_or(obs.temp_f, model["temp_f"]),
            "feels_like_f": _obs_or(feels_like, model["feels_like_f"]),
            "humidity_pct": _obs_or(obs.humidity_pct, model["humidity_pct"]),
            "wind_mph": _obs_or(obs.wind_mph, model["wind_mph"]),
            "code": model["code"] if obs.wmo_code is None else obs.wmo_code,
            "text": model["text"] if cond is None else cond["text"],
            "icon": model["icon"] if cond is None else cond["icon"],
        }
    )


def _stamp(utc_offset_seconds: int) -> str:
    """Now in the location's offset (per the API, not the Pi's zone)."""
    return datetime.now(_tz(utc_offset_seconds)).isoformat(timespec="seconds")


def _fetch_raw() -> dict[str, Any]:
    resp = _SESSION.get(
        _API_URL,
        params={
            **_PARAMS,
            "latitude": settings.weather_lat,
            "longitude": settings.weather_lon,
            # Read per call (not in _PARAMS, built at import) so test settings
            # overrides apply. Empty means the provider default.
            "models": settings.weather_model or "best_match",
        },
        timeout=_REQUEST_TIMEOUT_SECONDS,
    )
    resp.raise_for_status()
    data: dict[str, Any] = resp.json()
    return data


async def get_weather() -> WeatherBlock:
    """Raises on fetch/parse failure; the refresh loop keeps last-good."""
    raw = await asyncio.to_thread(_fetch_raw)
    data = normalize_weather(raw)
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
