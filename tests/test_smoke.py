"""Phase 1 smoke test — proves the app imports and the health route works.

Real source/cache tests land with their phases (3-6).
"""

from fastapi.testclient import TestClient

from app.main import app

# Bare TestClient (NOT used as a `with` context manager) on purpose: that skips
# the app lifespan, so the background refresh loop never starts and no real
# Open-Meteo/Proton network call is made during this test. Wrapping it in
# `with TestClient(app) as client:` would spin up the unkillable loop.
client = TestClient(app)


def test_healthz() -> None:
    resp = client.get("/healthz")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}
