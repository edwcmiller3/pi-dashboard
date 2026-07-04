"""/api/data route, cache-backed.

A bare TestClient (no `with`) does NOT run the app's lifespan, so the background
refresh loop never starts and no network call is made. The cache is redirected to
a per-test tmp dir by the autouse `_tmp_cache` fixture and populated directly to
exercise the route in isolation. The `clock_synced` fixture (see conftest) pins
`_clock_synced()` True so served docs are deterministic.
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import pytest
from fastapi.testclient import TestClient

from app import cache, main
from app.main import _CACHE_KEY, app

TZ = ZoneInfo("America/New_York")
NOW = datetime(2026, 7, 1, 9, 0, tzinfo=TZ)


def _stamp(dt: datetime) -> str:
    return dt.isoformat(timespec="seconds")


def test_api_data_503_until_cache_warm() -> None:
    resp = TestClient(app).get("/api/data")
    assert resp.status_code == 503


def test_api_data_serves_cached_doc(clock_synced: Path) -> None:
    # Partial (not full-DashboardDoc) on purpose: the route serves whatever the
    # cache holds verbatim, only overlaying the live clock_synced — so a minimal
    # doc is enough to prove that pass-through.
    doc: dict[str, Any] = {
        "weather": {"ok": True},
        "calendar": {"ok": False, "events": []},
    }
    cache.write(_CACHE_KEY, doc)
    resp = TestClient(app).get("/api/data")
    assert resp.status_code == 200
    # clock_synced is overlaid live at serve time on top of the cached doc.
    assert resp.json() == {**doc, "clock_synced": True}


def test_api_data_clock_synced_is_computed_live_not_from_cache(
    clock_synced: Path,
) -> None:
    """The boot refresh tick stamps clock_synced=False (NTP not yet synced).
    /api/data must override that stale cached value with the live clock state, so
    the warning clears within one frontend poll of sync, not at the next 15-min
    refresh that rebuilds the doc."""
    stale: dict[str, Any] = {
        "weather": {"ok": True},
        "calendar": {"ok": True, "events": []},
        "clock_synced": False,  # baked in by the pre-sync boot tick
    }
    cache.write(_CACHE_KEY, stale)
    # `clock_synced` fixture has the live marker present -> overrides cached False.
    resp = TestClient(app).get("/api/data")
    assert resp.status_code == 200
    assert resp.json()["clock_synced"] is True


def test_api_data_tolerates_non_dict_cached_value() -> None:
    # cache.read returns Any; a non-dict cached value (only reachable via a
    # corrupt / externally-mangled cache file) must not crash the `{**doc, ...}`
    # clock overlay. The isinstance(doc, dict) guard skips the overlay and serves
    # the value as-is with 200 — an honest degrade, never a 500.
    cache.write(_CACHE_KEY, [1, 2, 3])
    resp = TestClient(app).get("/api/data")
    assert resp.status_code == 200
    assert resp.json() == [1, 2, 3]


def test_post_refresh_forces_a_refresh(monkeypatch: pytest.MonkeyPatch) -> None:
    # POST /refresh forces an immediate refresh of every source (sources
    # monkeypatched so no network call is made). A bare TestClient runs no
    # lifespan, so only this request drives the loop.
    async def fake_weather() -> dict[str, Any]:
        return {
            "ok": True,
            "fetched_at": _stamp(NOW),
            "current": {"temp_f": 71},
            "forecast": [],
        }

    async def fake_calendar(now: Any = None, last_good: Any = None) -> dict[str, Any]:
        return {"ok": True, "fetched_at": _stamp(NOW), "events": []}

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
    async def boom() -> dict[str, Any]:
        raise RuntimeError("open-meteo down")

    async def fake_calendar(now: Any = None, last_good: Any = None) -> dict[str, Any]:
        return {"ok": True, "fetched_at": _stamp(NOW), "events": []}

    monkeypatch.setattr(main, "get_weather", boom)
    monkeypatch.setattr(main, "get_calendar", fake_calendar)

    resp = TestClient(app).post("/refresh")
    assert resp.status_code == 502
    assert cache.read(_CACHE_KEY) is None
