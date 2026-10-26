"""Static-asset deploy freshness.

`StaticFiles` sends no `Cache-Control`, so the kiosk could keep a stale bundle
after a same-day `git pull`. Every static response carries `no-cache` (not
`no-store`): the browser must revalidate, getting a cheap 304 when unchanged,
so a deploy lands on the next page load.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.main import app


@pytest.mark.parametrize(
    "path",
    [
        "/",
        "/index.html",
        "/app.js",
        "/style.css",
        "/core/contract.js",
        "/core/time.js",
        "/core/agenda.js",
        "/core/format.js",
        "/core/dom.js",
        "/core/machine.js",
        "/core/chrome.js",
        "/core/router.js",
        "/core/admin.js",
        "/core/admin-panels.js",
        "/layouts/classic/admin.js",
        "/layouts/classic/admin.css",
        "/layouts/hud/admin.js",
        "/layouts/hud/admin.css",
        "/layouts/swiss-mono/admin.js",
        "/layouts/swiss-mono/admin.css",
        "/packs/weather-icons/pack.css",
        "/packs/weather-icons/index.js",
        "/packs/meteocons-flat/pack.css",
        "/packs/meteocons-flat/index.js",
        "/packs/meteocons-line/pack.css",
        "/packs/meteocons-line/index.js",
        "/packs/meteocons-mono/pack.css",
        "/packs/meteocons-mono/index.js",
        "/layouts/classic/index.js",
        "/layouts/classic/layout.css",
        "/layouts/hud/index.js",
        "/layouts/hud/layout.css",
        "/layouts/hud/geometry/scale.js",
        "/layouts/hud/geometry/dial.js",
        "/layouts/hud/geometry/solar.js",
        "/layouts/hud/geometry/forecast.js",
    ],
)
def test_static_assets_send_no_cache(path: str) -> None:
    resp = TestClient(app).get(path)
    assert resp.status_code == 200
    assert resp.headers["cache-control"] == "no-cache"


def test_static_revalidation_validators_present() -> None:
    # no-cache needs a validator to 304 against.
    resp = TestClient(app).get("/app.js")
    assert resp.headers.get("etag")
    assert resp.headers.get("last-modified")
