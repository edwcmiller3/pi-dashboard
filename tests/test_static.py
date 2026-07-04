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

import re

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


# ── Frosted-glass progressive enhancement ────────────────────────────────────
# The frosted-glass build is a PURE-CSS progressive enhancement. Its visual
# result and repaint smoothness are validated on the panel, not here — that
# can't be unit-tested. The ONE invariant worth guarding automatically is the
# fallback contract: `backdrop-filter` (the GPU-expensive op) must never be
# reachable on a software compositor. It ships gated by BOTH `@supports` (feature
# query) AND a `.glass-blur` opt-in class, so removing that one class reverts to
# the safe build. These text-level checks guard against a future edit
# accidentally making the blur unconditional and breaking the SW-render floor.


def _supports_blocks(css: str) -> list[str]:
    """Return the body text of every top-level `@supports (...) { ... }` block.

    A hand-rolled brace matcher (no CSS-parser dependency); adequate because the
    stylesheet's only nested at-rule is this one enhancement block.
    """
    blocks: list[str] = []
    marker = "@supports"
    idx = css.find(marker)
    while idx != -1:
        open_brace = css.find("{", idx)
        depth, j = 1, open_brace + 1
        while j < len(css) and depth:
            depth += (css[j] == "{") - (css[j] == "}")
            j += 1
        blocks.append(css[open_brace + 1 : j - 1])
        idx = css.find(marker, j)
    return blocks


def test_glass_blur_is_gated_by_supports_and_optin_class() -> None:
    # Strip `/* ... */` comments first so prose mentions of `@supports` /
    # `backdrop-filter` in the stylesheet's docs can't skew the structural checks.
    raw = TestClient(app).get("/style.css").text
    css = re.sub(r"/\*.*?\*/", "", raw, flags=re.DOTALL)

    # Fallback contract: a `.glass` rule with a solid-ish fill must exist OUTSIDE
    # any @supports block, so a compositor without backdrop-filter still gets the
    # safe surface. (Everything before the first @supports is un-gated CSS.)
    ungated = css.split("@supports", 1)[0]
    assert ".glass {" in ungated
    assert "background:" in ungated.split(".glass {", 1)[1]

    # Every backdrop-filter DECLARATION (prefixed or not — `-webkit-backdrop-
    # filter:` ends in the same `backdrop-filter:` substring) must live inside an
    # @supports block, and never in the un-gated CSS. The colon form ignores
    # prose mentions of the property in comments.
    assert "backdrop-filter:" not in ungated

    supports_bodies = _supports_blocks(css)
    assert supports_bodies, "expected an @supports block for the frosted-glass build"
    blur_bodies = [b for b in supports_bodies if "backdrop-filter:" in b]
    assert blur_bodies, "backdrop-filter must be declared inside @supports"

    # …and each such block must scope the blur under the `.glass-blur` opt-in, so
    # the enhancement is off unless the class is present on the container.
    for body in blur_bodies:
        assert ".glass-blur" in body
