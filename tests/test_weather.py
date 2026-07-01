"""Phase 3 — weather adapter tests.

The heart of this is `normalize_weather`, the pure transform from raw Open-Meteo
JSON to the contract's `weather` block (written test-first). `get_weather` is the
thin async wrapper around the offloaded `requests` fetch; it's exercised with the
network call monkeypatched out so the suite stays offline.

`RAW` stays `dict[str, Any]`: it models the *raw external* Open-Meteo response,
the one genuinely-untyped boundary (the contract docstring blesses `Any` there),
and `normalize_weather` takes `dict[str, Any]`. Variants are built through the
`with_current`/`with_daily` helpers so the pervasive `{**RAW, "current": {...}}`
spreading lives in one place.
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


def with_current(**overrides: Any) -> dict[str, Any]:
    """A copy of RAW with `current` fields overridden — collapses the repeated
    `{**RAW, "current": {**RAW["current"], ...}}` fixture-building."""
    return {**RAW, "current": {**RAW["current"], **overrides}}


def with_daily(**overrides: Any) -> dict[str, Any]:
    """A copy of RAW with `daily` series overridden (same idea as with_current)."""
    return {**RAW, "daily": {**RAW["daily"], **overrides}}


# ── _round_half_up: displayed numbers round halves UP, not banker's ───────────


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (72.3, 72),  # rounds down
        (72.4, 72),
        (72.5, 73),  # .5 UP — banker's (round-half-to-even) would give 72
        (74.5, 75),  # .5 UP — banker's would give 74
        (71.5, 72),  # .5 UP where the even neighbor is also up (both agree)
        (6.5, 7),
        (0.5, 1),
        (-0.5, 0),  # halfway toward zero still rounds up (toward +inf)
        (61.2, 61),
    ],
)
def test_round_half_up(value: float, expected: int) -> None:
    assert weather._round_half_up(value) == expected


# ── normalize_weather: current ──────────────────────────────────────────────


def test_current_numbers_rounded_to_int() -> None:
    cur = weather.normalize_weather(RAW)["current"]
    assert cur["temp_f"] == 72  # 72.3 -> 72
    assert cur["feels_like_f"] == 70  # 70.1 -> 70
    assert cur["humidity_pct"] == 44
    assert cur["wind_mph"] == 6  # 6.2 -> 6
    assert cur["high_f"] == 75  # daily.max[0] 75.4 -> 75
    assert cur["low_f"] == 61  # daily.min[0] 61.2 -> 61


def test_current_icon_text_resolved_day() -> None:
    cur = weather.normalize_weather(RAW)["current"]
    assert cur["code"] == 0
    assert cur["text"] == "Clear"
    assert cur["icon"] == "wi-day-sunny"  # is_day=1
    assert cur["is_day"] is True


def test_current_icon_uses_night_variant_when_not_day() -> None:
    cur = weather.normalize_weather(with_current(is_day=0))["current"]
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
    assert first["precip_expected"] is False  # code 2 (partly cloudy) is dry


def test_forecast_precip_expected_tracks_the_weather_code() -> None:
    # The precip line is gated on is_wet(code), not the % — a dry code hides it
    # even at a nonzero %, a wet code shows it. daily[2] (forecast[1]) is code 63.
    fc = weather.normalize_weather(RAW)["forecast"]
    assert fc[1]["code"] == 63 and fc[1]["precip_expected"] is True  # rain
    assert all(f["precip_expected"] is False for f in (fc[0], fc[2], fc[3]))


def test_forecast_uses_daytime_icons_regardless_of_current_is_day() -> None:
    # Even fetched at night, the look-ahead cards show day glyphs.
    fc = weather.normalize_weather(with_current(is_day=0))["forecast"]
    assert fc[1]["icon"] == "wi-day-rain"  # code 63 daytime


# ── robustness ──────────────────────────────────────────────────────────────


def test_null_precip_probability_becomes_zero() -> None:
    # Open-Meteo can return null for precipitation_probability_max.
    norm = weather.normalize_weather(
        with_daily(precipitation_probability_max=[None, None, 80, 5, 10])
    )
    assert norm["current"]["precip_prob_pct"] == 0
    assert norm["forecast"][0]["precip_prob_pct"] == 0


def test_unknown_code_falls_back_to_wi_na() -> None:
    cur = weather.normalize_weather(with_current(weather_code=1234))["current"]
    assert cur["icon"] == "wi-na"
    assert cur["text"] == "Unknown"


def test_short_daily_response_raises_clear_valueerror() -> None:
    # A truncated Open-Meteo payload (<5 daily entries) used to raise a cryptic
    # IndexError from the daily[1:5] slice / daily[0] index. Guard it into a
    # descriptive ValueError so the refresh loop logs an intelligible cause and
    # keeps the last-good doc (all-or-nothing keep-last-good is deliberate — the
    # frontend never renders a half-built weather block). Truncate ONLY `time`
    # (the field the guard measures) so the assertion pins that specific guard.
    raw = with_daily(time=RAW["daily"]["time"][:2])  # 2 days, other series full
    with pytest.raises(ValueError, match="too short"):
        weather.normalize_weather(raw)


def test_missing_current_block_raises_clear_valueerror() -> None:
    # A response missing `current` -> a legible ValueError, not a bare KeyError.
    with pytest.raises(ValueError, match="current"):
        weather.normalize_weather({"daily": RAW["daily"]})


def test_missing_daily_block_raises_clear_valueerror() -> None:
    # The other branch of the top-level guard: `daily` absent -> legible error.
    with pytest.raises(ValueError, match="daily"):
        weather.normalize_weather({"current": RAW["current"]})


@pytest.mark.parametrize("key", ["sunrise", "sunset"])
def test_null_polar_sunrise_or_sunset_raises_clear_valueerror(key: str) -> None:
    # Open-Meteo returns null sunrise/sunset at polar latitudes (no rise/set on a
    # polar day/night), and lat/lon is user-configurable. A null today[0] would be
    # a cryptic TypeError out of `_with_offset`; guard it into a legible ValueError
    # so the loop keeps last-good (all-or-nothing), same as the short-series guard.
    raw = with_daily(**{key: [None, *RAW["daily"][key][1:]]})
    with pytest.raises(ValueError, match=key):
        weather.normalize_weather(raw)


# ── get_weather: async wrapper (network monkeypatched out) ───────────────────


def test_get_weather_wraps_with_ok_and_offset_stamp(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(weather, "_fetch_raw", lambda: RAW)
    result = asyncio.run(weather.get_weather())
    assert result["ok"] is True
    # fetched_at stamped in the API's local offset (-14400 -> -04:00), with offset.
    fetched_at = result["fetched_at"]
    assert fetched_at is not None
    assert fetched_at.endswith("-04:00")
    assert "T" in fetched_at
    # the normalized block rides along under the same dict (rounding itself is
    # covered by test_round_half_up / test_current_numbers_rounded_to_int).
    assert result["current"]["icon"] == "wi-day-sunny"
    assert len(result["forecast"]) == 4
