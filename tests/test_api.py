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
    doc = {"weather": {"ok": True}, "calendar": {"ok": False, "events": []}}
    cache.write(_CACHE_KEY, doc)
    resp = TestClient(app).get("/api/data")
    assert resp.status_code == 200
    assert resp.json() == doc


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
