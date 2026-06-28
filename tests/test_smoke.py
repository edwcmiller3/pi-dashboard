"""Phase 1 smoke test — proves the app imports and the health route works.

Real source/cache tests land with their phases (3-6).
"""

from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def test_healthz():
    resp = client.get("/healthz")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}
