"""Shared pytest fixtures and typed source-block factories.

The block factories build real `WeatherBlock`/`CalendarBlock` values (not
`dict[str, Any]`), so a test fake that drifts from the contract fails the
type-check instead of silently passing.

Route tests use a bare `TestClient(app)`, never `with TestClient(app)`: the
`with` form runs the lifespan, starting the refresh loop and its real network
calls.
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest

from app.config import settings
from app.contract import CalendarBlock, CurrentWeather, WeatherBlock


def current_weather(temp_f: int) -> CurrentWeather:
    return {
        "temp_f": temp_f,
        "feels_like_f": temp_f,
        "code": 0,
        "text": "Clear",
        "icon": "clear-day",
        "is_day": True,
        "humidity_pct": 50,
        "wind_mph": 5,
        "precip_prob_pct": 0,
        "high_f": temp_f + 5,
        "low_f": temp_f - 5,
        "sunrise": "2026-07-01T06:00:00-04:00",
        "sunset": "2026-07-01T20:00:00-04:00",
    }


def weather_block(
    *,
    temp_f: int,
    fetched_at: str | None,
    ok: bool = True,
    ttl: int | None = None,
    attempted_at: str | None = None,
) -> WeatherBlock:
    block: WeatherBlock = {
        "ok": ok,
        "fetched_at": fetched_at,
        "current": current_weather(temp_f),
        "forecast": [],
    }
    if ttl is not None:
        block["ttl"] = ttl
    if attempted_at is not None:
        block["attempted_at"] = attempted_at
    return block


def calendar_block(
    *,
    fetched_at: str | None,
    ok: bool = True,
    ttl: int | None = None,
    attempted_at: str | None = None,
) -> CalendarBlock:
    block: CalendarBlock = {"ok": ok, "fetched_at": fetched_at, "events": []}
    if ttl is not None:
        block["ttl"] = ttl
    if attempted_at is not None:
        block["attempted_at"] = attempted_at
    return block


@pytest.fixture(autouse=True)
def _tmp_cache(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """Keep every test off the real `var/` cache (and its live last-good doc).
    Tests needing a different cache dir override `cache_dir` themselves."""
    monkeypatch.setattr(settings, "cache_dir", str(tmp_path))


@pytest.fixture(autouse=True)
def _default_weather_settings(monkeypatch: pytest.MonkeyPatch) -> None:
    """Pin the weather-source settings to their shipped defaults.

    `settings` reads the real `.env` at import, so on a checkout with
    NWS_STATION set the off-by-default tests fail and `get_weather` tests make
    a live api.weather.gov call. Tests needing overrides re-set them in their
    own body."""
    monkeypatch.setattr(settings, "nws_station", "")
    monkeypatch.setattr(settings, "weather_model", "best_match")


@pytest.fixture
def clock_synced(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Iterator[Path]:
    """Make `main._clock_synced()` report True. Yields the marker path so a test
    can unlink it to flip the state."""
    from app import main

    marker = tmp_path / "synchronized"
    marker.write_text("", encoding="utf-8")
    monkeypatch.setattr(main, "_TIMESYNC_MARKER", marker)
    yield marker
