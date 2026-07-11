"""Static-asset deploy freshness.

`StaticFiles` stamps ETag/Last-Modified but no `Cache-Control`, so a browser may
reuse an old `app.js`/`style.css`/`index.html` after a `git pull` until something
busts the cache (hard refresh, the next 06:00 cold boot). On the
kiosk that means a same-day deploy can be silently masked by a stale cached
bundle. We send `Cache-Control: no-cache` on every static response: the browser
keeps its copy but MUST revalidate (cheap 304 over localhost when unchanged, a
full 200 the instant the file differs), so a deploy lands on the next page load.

`no-cache` (revalidate), not `no-store` (never cache): the ETag short-circuits to
a 304 when nothing changed, which is free correctness — the assets ARE cacheable,
they just must be revalidated. The data path is unaffected: `/api/data` is a
separate JSON route the frontend already fetches with `cache:"no-store"`.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.main import app

# NOTE: every request below uses a bare `TestClient(app).get(...)` — never the
# `with TestClient(app) as client:` form. That is load-bearing: the `with` form
# runs the app lifespan, which starts the unkillable background refresh loop and
# would fire real Open-Meteo/Proton network calls during these header-only tests.
# Keep these bare so the static-asset checks stay hermetic.


@pytest.mark.parametrize("path", ["/", "/index.html", "/app.js", "/style.css"])
def test_static_assets_send_no_cache(path: str) -> None:
    resp = TestClient(app).get(path)
    assert resp.status_code == 200
    assert resp.headers["cache-control"] == "no-cache"


def test_static_revalidation_validators_present() -> None:
    # no-cache is only useful if the response carries a validator to 304 against;
    # StaticFiles supplies etag + last-modified — assert we didn't strip them.
    resp = TestClient(app).get("/app.js")
    assert resp.headers.get("etag")
    assert resp.headers.get("last-modified")
