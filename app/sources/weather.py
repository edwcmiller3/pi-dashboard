"""Weather source — Open-Meteo.

Two layers, kept apart so the transform is pure and unit-testable:
  * `normalize_weather(raw)` — pure: raw Open-Meteo JSON -> the contract's
    `weather` block (`current` + 4 future-day `forecast`). The frontend never
    sees raw WMO codes; `icon`/`text` are resolved here via `weather_codes`.
  * `get_weather()` — impure: the single Open-Meteo call, offloaded off the
    event loop via `asyncio.to_thread` (spec §5), wrapped with `ok`/`fetched_at`.

Param set confirmed live 2026-06-28 (0.D4 + the v4 expanded-fields decision):
one request, no extra dependency. `forecast_days=5` returns today + 4 future;
the cards use `daily[1:5]`, the hero uses `daily[0]`.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from typing import Any

import requests

from app.config import settings
from app.weather_codes import describe

_API_URL = "https://api.open-meteo.com/v1/forecast"

# current.precipitation/precipitation_unit are requested for parity with the
# confirmed param set; the contract surfaces precip *probability* (from daily),
# not the current precip *amount*, so that field is fetched but not mapped.
_PARAMS: dict[str, Any] = {
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

_REQUEST_TIMEOUT_SECONDS = 10


def _pct(value: Any) -> int:
    """precipitation_probability_max can be null in the feed -> treat as 0%."""
    return 0 if value is None else round(value)


def _forecast_day(daily: dict[str, Any], i: int) -> dict[str, Any]:
    """One look-ahead card from `daily` index `i`. Cards always use day glyphs."""
    cond = describe(int(daily["weather_code"][i]), is_day=True)
    return {
        "date": daily["time"][i],
        "code": int(daily["weather_code"][i]),
        "text": cond["text"],
        "icon": cond["icon"],
        "high_f": round(daily["temperature_2m_max"][i]),
        "low_f": round(daily["temperature_2m_min"][i]),
        "precip_prob_pct": _pct(daily["precipitation_probability_max"][i]),
    }


def normalize_weather(raw: dict[str, Any]) -> dict[str, Any]:
    """Raw Open-Meteo JSON -> the contract's `weather` block (pure)."""
    cur = raw["current"]
    daily = raw["daily"]
    is_day = bool(cur["is_day"])
    cond = describe(int(cur["weather_code"]), is_day)
    current = {
        "temp_f": round(cur["temperature_2m"]),
        "feels_like_f": round(cur["apparent_temperature"]),
        "code": int(cur["weather_code"]),
        "text": cond["text"],
        "icon": cond["icon"],
        "is_day": is_day,
        "humidity_pct": round(cur["relative_humidity_2m"]),
        "wind_mph": round(cur["wind_speed_10m"]),
        # hero precip% = TODAY's daily max (current block has no probability)
        "precip_prob_pct": _pct(daily["precipitation_probability_max"][0]),
        "high_f": round(daily["temperature_2m_max"][0]),
        "low_f": round(daily["temperature_2m_min"][0]),
        # naive-local ISO from timezone=auto; the frontend renders the wall-clock
        "sunrise": daily["sunrise"][0],
        "sunset": daily["sunset"][0],
    }
    # Cards = the 4 FUTURE days (daily[1:5]); today (daily[0]) feeds the hero.
    forecast = [_forecast_day(daily, i) for i in range(1, 5)]
    return {"current": current, "forecast": forecast}


def _stamp(utc_offset_seconds: int) -> str:
    """Stamp "now" in the dashboard location's offset (per the API, not the Pi
    clock), as ISO with an explicit offset — so the frontend renders the right
    wall-clock and compares instants correctly."""
    tz = timezone(timedelta(seconds=utc_offset_seconds))
    return datetime.now(tz).isoformat(timespec="seconds")


def _fetch_raw() -> dict[str, Any]:
    """The blocking Open-Meteo call (runs in a worker thread)."""
    resp = requests.get(
        _API_URL,
        params={
            **_PARAMS,
            "latitude": settings.weather_lat,
            "longitude": settings.weather_lon,
        },
        timeout=_REQUEST_TIMEOUT_SECONDS,
    )
    resp.raise_for_status()
    data: dict[str, Any] = resp.json()
    return data


async def get_weather() -> dict[str, Any]:
    """Fetch + normalize, wrapped with `ok`/`fetched_at` for the contract.

    The blocking `requests` call is offloaded so the event loop never stalls.
    Raises on fetch/parse failure — the refresh loop catches it and keeps the
    last-good cached doc (per-source soft-fail / cache fallback is Phase 6).
    """
    raw = await asyncio.to_thread(_fetch_raw)
    return {
        "ok": True,
        "fetched_at": _stamp(int(raw["utc_offset_seconds"])),
        **normalize_weather(raw),
    }
