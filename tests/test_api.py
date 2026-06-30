"""Phase 3 — /api/data route, cache-backed.

A bare TestClient (no `with`) does NOT run the app's lifespan, so the background
refresh loop never starts and no network call is made. The cache is redirected
to a tmp dir and populated directly to exercise the route in isolation.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from app import cache, main
from app.config import settings
from app.main import _CACHE_KEY, app


def test_api_data_503_until_cache_warm(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(settings, "cache_dir", str(tmp_path))
    resp = TestClient(app).get("/api/data")
    assert resp.status_code == 503


def test_api_data_serves_cached_doc(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(settings, "cache_dir", str(tmp_path))
    # Pin the live clock-sync check so the served doc is deterministic: parent dir
    # present + marker present -> _clock_synced() is True (see test_refresh).
    marker = tmp_path / "synchronized"
    marker.write_text("")
    monkeypatch.setattr(main, "_TIMESYNC_MARKER", marker)
    doc = {"weather": {"ok": True}, "calendar": {"ok": False, "events": []}}
    cache.write(_CACHE_KEY, doc)
    resp = TestClient(app).get("/api/data")
    assert resp.status_code == 200
    # clock_synced is overlaid live at serve time on top of the cached doc.
    assert resp.json() == {**doc, "clock_synced": True}


def test_api_data_clock_synced_is_computed_live_not_from_cache(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """The boot refresh tick stamps clock_synced=False (NTP not yet synced).
    /api/data must override that stale cached value with the live clock state, so
    the warning clears within one frontend poll of sync, not at the next 15-min
    refresh that rebuilds the doc."""
    monkeypatch.setattr(settings, "cache_dir", str(tmp_path))
    stale = {
        "weather": {"ok": True},
        "calendar": {"ok": True, "events": []},
        "clock_synced": False,  # baked in by the pre-sync boot tick
    }
    cache.write(_CACHE_KEY, stale)
    # Clock has since synced: live marker present overrides the cached False.
    marker = tmp_path / "synchronized"
    marker.write_text("")
    monkeypatch.setattr(main, "_TIMESYNC_MARKER", marker)
    resp = TestClient(app).get("/api/data")
    assert resp.status_code == 200
    assert resp.json()["clock_synced"] is True


def test_post_refresh_forces_a_refresh(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    # POST /refresh forces an immediate refresh of every source (sources
    # monkeypatched so no network call is made). A bare TestClient runs no
    # lifespan, so only this request drives the loop.
    monkeypatch.setattr(settings, "cache_dir", str(tmp_path))

    async def fake_weather() -> dict[str, Any]:
        return {
            "ok": True,
            "fetched_at": "2026-07-01T09:00:00-04:00",
            "current": {"temp_f": 71},
            "forecast": [],
        }

    async def fake_calendar(now: Any = None, last_good: Any = None) -> dict[str, Any]:
        return {"ok": True, "fetched_at": "2026-07-01T09:00:00-04:00", "events": []}

    monkeypatch.setattr(main, "get_weather", fake_weather)
    monkeypatch.setattr(main, "get_calendar", fake_calendar)

    resp = TestClient(app).post("/refresh")
    assert resp.status_code == 200
    assert resp.json() == {"status": "refreshed"}
    doc = cache.read(_CACHE_KEY)
    assert doc is not None and doc["weather"]["current"]["temp_f"] == 71


def test_post_refresh_502_on_cold_boot_failure(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    # No cache + weather fetch fails -> the forced tick raises -> 502 (and the
    # cache stays empty, so /api/data remains an honest 503).
    monkeypatch.setattr(settings, "cache_dir", str(tmp_path))

    async def boom() -> dict[str, Any]:
        raise RuntimeError("open-meteo down")

    async def fake_calendar(now: Any = None, last_good: Any = None) -> dict[str, Any]:
        return {"ok": True, "fetched_at": None, "events": []}

    monkeypatch.setattr(main, "get_weather", boom)
    monkeypatch.setattr(main, "get_calendar", fake_calendar)

    resp = TestClient(app).post("/refresh")
    assert resp.status_code == 502
    assert cache.read(_CACHE_KEY) is None
