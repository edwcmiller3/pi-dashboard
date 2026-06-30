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
import math
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

# forecast_days=5 -> today (hero) + 4 future (cards). The normalize step indexes
# daily[0] and slices daily[1:5], so a shorter series can't build a full block.
_REQUIRED_DAILY_DAYS = 5


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


def _forecast_day(daily: dict[str, Any], i: int) -> dict[str, Any]:
    """One look-ahead card from `daily` index `i`. Cards always use day glyphs."""
    cond = describe(int(daily["weather_code"][i]), is_day=True)
    return {
        "date": daily["time"][i],
        "code": int(daily["weather_code"][i]),
        "text": cond["text"],
        "icon": cond["icon"],
        "high_f": _round_half_up(daily["temperature_2m_max"][i]),
        "low_f": _round_half_up(daily["temperature_2m_min"][i]),
        "precip_prob_pct": _pct(daily["precipitation_probability_max"][i]),
    }


def _require(raw: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    """Validate the shape `normalize_weather` indexes into, turning a cryptic
    KeyError/IndexError on a malformed or truncated payload into a legible
    ValueError. The transform stays all-or-nothing: a bad response raises and
    the refresh loop keeps the last-good doc rather than rendering a partial
    weather block (per-field tolerance was rejected — see the Phase-6 notes)."""
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
    return cur, daily


def normalize_weather(raw: dict[str, Any]) -> dict[str, Any]:
    """Raw Open-Meteo JSON -> the contract's `weather` block (pure)."""
    cur, daily = _require(raw)
    tz = _tz(int(raw["utc_offset_seconds"]))
    is_day = bool(cur["is_day"])
    cond = describe(int(cur["weather_code"]), is_day)
    current = {
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


def _stamp(utc_offset_seconds: int) -> str:
    """Stamp "now" in the dashboard location's offset (per the API, not the Pi
    clock), as ISO with an explicit offset — so the frontend renders the right
    wall-clock and compares instants correctly."""
    return datetime.now(_tz(utc_offset_seconds)).isoformat(timespec="seconds")


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
