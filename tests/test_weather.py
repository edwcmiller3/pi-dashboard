"""Phase 3 — weather adapter tests.

The heart of this is `normalize_weather`, the pure transform from raw Open-Meteo
JSON to the contract's `weather` block (written test-first). `get_weather` is the
thin async wrapper around the offloaded `requests` fetch; it's exercised with the
network call monkeypatched out so the suite stays offline.
"""

from __future__ import annotations

import asyncio
from typing import Any

import pytest

from app.sources import weather

# A realistic single-call Open-Meteo response (shape confirmed live in 0.D4 +
# the v4 expanded-fields decision). timezone=auto -> naive-local time strings;
# utc_offset_seconds carries the offset. 5 daily entries: today + 4 future.
RAW: dict[str, Any] = {
    "latitude": 36.0,
    "longitude": -84.1,
    "timezone": "America/New_York",
    "utc_offset_seconds": -14400,  # EDT, -04:00
    "current": {
        "time": "2026-06-29T09:40",
        "temperature_2m": 72.3,
        "apparent_temperature": 70.1,
        "relative_humidity_2m": 44,
        "weather_code": 0,
        "is_day": 1,
        "wind_speed_10m": 6.2,
        "precipitation": 0.0,
    },
    "daily": {
        "time": ["2026-06-29", "2026-06-30", "2026-07-01", "2026-07-02", "2026-07-03"],
        "weather_code": [0, 2, 63, 0, 1],
        "temperature_2m_max": [75.4, 78.1, 70.3, 76.0, 74.2],
        "temperature_2m_min": [61.2, 63.4, 59.1, 60.0, 58.3],
        "precipitation_probability_max": [10, 20, 80, 5, 10],
        "sunrise": [
            "2026-06-29T06:18",
            "2026-06-30T06:19",
            "2026-07-01T06:19",
            "2026-07-02T06:20",
            "2026-07-03T06:20",
        ],
        "sunset": [
            "2026-06-29T20:51",
            "2026-06-30T20:51",
            "2026-07-01T20:51",
            "2026-07-02T20:51",
            "2026-07-03T20:50",
        ],
    },
}


# ── normalize_weather: current ──────────────────────────────────────────────


def test_current_numbers_rounded_to_int() -> None:
    cur = weather.normalize_weather(RAW)["current"]
    assert cur["temp_f"] == 72  # 72.3 -> 72
    assert cur["feels_like_f"] == 70  # 70.1 -> 70
    assert cur["humidity_pct"] == 44
    assert cur["wind_mph"] == 6  # 6.2 -> 6
    assert cur["high_f"] == 75  # daily.max[0] 75.4 -> 75
    assert cur["low_f"] == 61  # daily.min[0] 61.2 -> 61


def test_numbers_round_half_up_not_bankers() -> None:
    # .5 rounds UP (73), not Python's default round-half-to-even (which gives 72).
    cur = {**RAW["current"], "temperature_2m": 72.5, "wind_speed_10m": 6.5}
    daily = {**RAW["daily"], "temperature_2m_max": [80.5, 78.1, 70.3, 76.0, 74.2]}
    raw = {**RAW, "current": cur, "daily": daily}
    norm = weather.normalize_weather(raw)
    assert norm["current"]["temp_f"] == 73
    assert norm["current"]["wind_mph"] == 7
    assert norm["current"]["high_f"] == 81


def test_current_icon_text_resolved_day() -> None:
    cur = weather.normalize_weather(RAW)["current"]
    assert cur["code"] == 0
    assert cur["text"] == "Clear"
    assert cur["icon"] == "wi-day-sunny"  # is_day=1
    assert cur["is_day"] is True


def test_current_icon_uses_night_variant_when_not_day() -> None:
    raw = {**RAW, "current": {**RAW["current"], "is_day": 0}}
    cur = weather.normalize_weather(raw)["current"]
    assert cur["icon"] == "wi-night-clear"
    assert cur["is_day"] is False


def test_current_precip_prob_is_todays_daily_max() -> None:
    # precip_prob for the hero comes from daily.precipitation_probability_max[0].
    cur = weather.normalize_weather(RAW)["current"]
    assert cur["precip_prob_pct"] == 10


def test_current_sunrise_sunset_emitted_with_offset() -> None:
    # Contract rule: every emitted time is ISO-local-WITH-offset. Open-Meteo
    # returns naive-local strings (timezone=auto), so we attach the location's
    # utc_offset_seconds (-14400 -> -04:00) — uniform with fetched_at/events,
    # and correct for any consumer that does `new Date(sunrise)`.
    cur = weather.normalize_weather(RAW)["current"]
    assert cur["sunrise"] == "2026-06-29T06:18:00-04:00"
    assert cur["sunset"] == "2026-06-29T20:51:00-04:00"


# ── normalize_weather: forecast (4 future days = daily[1:5]) ─────────────────


def test_forecast_is_four_future_days() -> None:
    fc = weather.normalize_weather(RAW)["forecast"]
    assert [f["date"] for f in fc] == [
        "2026-06-30",
        "2026-07-01",
        "2026-07-02",
        "2026-07-03",
    ]  # daily[1:5] — today (daily[0]) is excluded; it lives in the hero


def test_forecast_fields_resolved() -> None:
    first = weather.normalize_weather(RAW)["forecast"][0]
    assert first["code"] == 2
    assert first["text"] == "Partly cloudy"
    assert first["icon"] == "wi-day-cloudy"  # cards always use the daytime glyph
    assert first["high_f"] == 78
    assert first["low_f"] == 63
    assert first["precip_prob_pct"] == 20


def test_forecast_uses_daytime_icons_regardless_of_current_is_day() -> None:
    # Even fetched at night, the look-ahead cards show day glyphs.
    raw = {**RAW, "current": {**RAW["current"], "is_day": 0}}
    fc = weather.normalize_weather(raw)["forecast"]
    assert fc[1]["icon"] == "wi-day-rain"  # code 63 daytime


# ── robustness ──────────────────────────────────────────────────────────────


def test_null_precip_probability_becomes_zero() -> None:
    # Open-Meteo can return null for precipitation_probability_max.
    daily = {**RAW["daily"], "precipitation_probability_max": [None, None, 80, 5, 10]}
    raw = {**RAW, "daily": daily}
    norm = weather.normalize_weather(raw)
    assert norm["current"]["precip_prob_pct"] == 0
    assert norm["forecast"][0]["precip_prob_pct"] == 0


def test_unknown_code_falls_back_to_wi_na() -> None:
    raw = {**RAW, "current": {**RAW["current"], "weather_code": 1234}}
    cur = weather.normalize_weather(raw)["current"]
    assert cur["icon"] == "wi-na"
    assert cur["text"] == "Unknown"


def test_short_daily_response_raises_clear_valueerror() -> None:
    # A truncated Open-Meteo payload (<5 daily entries) used to raise a cryptic
    # IndexError from the daily[1:5] slice / daily[0] index. Guard it into a
    # descriptive ValueError so the refresh loop logs an intelligible cause and
    # keeps the last-good doc (all-or-nothing keep-last-good is deliberate — the
    # frontend never renders a half-built weather block).
    short = {k: v[:2] for k, v in RAW["daily"].items()}  # only 2 days
    raw = {**RAW, "daily": short}
    with pytest.raises(ValueError, match="daily"):
        weather.normalize_weather(raw)


def test_missing_top_level_block_raises_clear_valueerror() -> None:
    # A response missing `current`/`daily` entirely -> a legible ValueError, not
    # a bare KeyError.
    with pytest.raises(ValueError, match="current"):
        weather.normalize_weather({"daily": RAW["daily"]})


# ── get_weather: async wrapper (network monkeypatched out) ───────────────────


def test_get_weather_wraps_with_ok_and_offset_stamp(monkeypatch: Any) -> None:
    monkeypatch.setattr(weather, "_fetch_raw", lambda: RAW)
    result = asyncio.run(weather.get_weather())
    assert result["ok"] is True
    # fetched_at stamped in the API's local offset (-14400 -> -04:00), with offset.
    assert result["fetched_at"].endswith("-04:00")
    assert "T" in result["fetched_at"]
    # the normalized block rides along under the same dict
    assert result["current"]["temp_f"] == 72
    assert len(result["forecast"]) == 4
