"""Shared pytest fixtures and typed source-block factories.

The autouse `_tmp_cache` fixture redirects the JSON cache at `settings.cache_dir`
to a per-test `tmp_path` for EVERY test. That kills the ~20 duplicated
`monkeypatch.setattr(settings, "cache_dir", str(tmp_path))` lines that used to
open each cache-touching test AND guarantees no test can ever read or write the
real `var/` dir (a test that forgot the redirect used to be one edit away from
clobbering a live last-good doc). Tests that need a differently-shaped cache dir
(e.g. a not-yet-created nested path) still override `cache_dir` themselves — the
autouse fixture just sets a safe default first.

The block factories build real `WeatherBlock`/`CalendarBlock` values (not
`dict[str, Any]`), so any test fake that drifts from the contract fails the
type-check instead of silently passing. Shared here so every suite that fakes a
source (test_refresh, test_api, …) goes through the same typed discipline.
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
        "icon": "wi-day-sunny",
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
    """Point the cache at an isolated tmp dir for every test (see module docs)."""
    monkeypatch.setattr(settings, "cache_dir", str(tmp_path))


@pytest.fixture(autouse=True)
def _default_weather_settings(monkeypatch: pytest.MonkeyPatch) -> None:
    """Pin the weather-source settings to their shipped defaults for every test.

    `settings` reads the developer's real `.env` at import, so without this a
    deployed checkout (NWS_STATION set — the feature's normal end state) fails
    the tests that assert off-by-default behavior AND lets `get_weather` tests
    that only patch `_fetch_raw` make a live api.weather.gov call mid-suite —
    a network-dependent, weather-dependent flake. Tests that need overrides
    re-set these in their own body (which runs after autouse fixtures)."""
    monkeypatch.setattr(settings, "nws_station", "")
    monkeypatch.setattr(settings, "weather_model", "best_match")


@pytest.fixture
def clock_synced(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Iterator[Path]:
    """Make `main._clock_synced()` report True: the timesyncd runtime dir exists
    (its parent, `tmp_path`) and the `synchronized` marker is present. Yields the
    marker path so a test can flip the state (e.g. unlink it) if needed."""
    from app import main

    marker = tmp_path / "synchronized"
    marker.write_text("", encoding="utf-8")
    monkeypatch.setattr(main, "_TIMESYNC_MARKER", marker)
    yield marker
