"""/api/data and POST /refresh, cache-backed. Tests populate the cache directly;
with no lifespan running, only POST /refresh drives a tick."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import pytest
from conftest import calendar_block, weather_block
from fastapi.testclient import TestClient

from app import cache, main
from app.contract import CalendarBlock, WeatherBlock
from app.main import _CACHE_KEY, app

TZ = ZoneInfo("America/New_York")
NOW = datetime(2026, 7, 1, 9, 0, tzinfo=TZ)


def _stamp(dt: datetime) -> str:
    return dt.isoformat(timespec="seconds")


def test_api_data_503_until_cache_warm() -> None:
    resp = TestClient(app).get("/api/data")
    assert resp.status_code == 503


def test_api_data_serves_cached_doc(clock_synced: Path) -> None:
    # Partial doc on purpose: the route serves the cache verbatim apart from the
    # clock_synced overlay.
    doc: dict[str, Any] = {
        "weather": {"ok": True},
        "calendar": {"ok": False, "events": []},
    }
    cache.write(_CACHE_KEY, doc)
    resp = TestClient(app).get("/api/data")
    assert resp.status_code == 200
    assert resp.json() == {**doc, "clock_synced": True}


def test_api_data_clock_synced_is_computed_live_not_from_cache(
    clock_synced: Path,
) -> None:
    """The boot tick caches clock_synced=False; serving the live value clears the
    warning within one poll of NTP sync, not at the next refresh."""
    stale: dict[str, Any] = {
        "weather": {"ok": True},
        "calendar": {"ok": True, "events": []},
        "clock_synced": False,  # baked in by the pre-sync boot tick
    }
    cache.write(_CACHE_KEY, stale)
    resp = TestClient(app).get("/api/data")
    assert resp.status_code == 200
    assert resp.json()["clock_synced"] is True


def test_api_data_tolerates_non_dict_cached_value() -> None:
    # Only reachable via a mangled cache file; it must not crash the `{**doc, ...}`
    # clock overlay into a 500.
    cache.write(_CACHE_KEY, [1, 2, 3])
    resp = TestClient(app).get("/api/data")
    assert resp.status_code == 200
    assert resp.json() == [1, 2, 3]


def test_post_refresh_forces_a_refresh(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake_weather() -> WeatherBlock:
        return weather_block(temp_f=71, fetched_at=_stamp(NOW))

    async def fake_calendar(
        now: datetime | None = None, last_good: CalendarBlock | None = None
    ) -> CalendarBlock:
        return calendar_block(fetched_at=_stamp(NOW))

    monkeypatch.setattr(main, "get_weather", fake_weather)
    monkeypatch.setattr(main, "get_calendar", fake_calendar)

    resp = TestClient(app).post("/refresh")
    assert resp.status_code == 200
    assert resp.json() == {"status": "refreshed"}
    doc = cache.read(_CACHE_KEY)
    assert doc is not None and doc["weather"]["current"]["temp_f"] == 71


def test_post_refresh_502_on_cold_boot_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # No cache + weather fetch fails -> the forced tick raises -> 502 (and the
    # cache stays empty, so /api/data remains an honest 503).
    async def boom() -> WeatherBlock:
        raise RuntimeError("open-meteo down")

    async def fake_calendar(
        now: datetime | None = None, last_good: CalendarBlock | None = None
    ) -> CalendarBlock:
        return calendar_block(fetched_at=_stamp(NOW))

    monkeypatch.setattr(main, "get_weather", boom)
    monkeypatch.setattr(main, "get_calendar", fake_calendar)

    resp = TestClient(app).post("/refresh")
    assert resp.status_code == 502
    assert cache.read(_CACHE_KEY) is None
