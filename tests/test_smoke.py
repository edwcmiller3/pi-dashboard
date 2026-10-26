"""Smoke test - proves the app imports and the health route works."""

from fastapi.testclient import TestClient

from app.main import app

# Bare, not `with`: see conftest.
client = TestClient(app)


def test_healthz() -> None:
    resp = client.get("/healthz")
    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"
