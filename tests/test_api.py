"""Phase 3 — /api/data route, cache-backed.

A bare TestClient (no `with`) does NOT run the app's lifespan, so the background
refresh loop never starts and no network call is made. The cache is redirected
to a tmp dir and populated directly to exercise the route in isolation.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app import cache
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
