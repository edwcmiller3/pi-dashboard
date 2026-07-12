"""The /theme.css palette-override route (THEME setting).

The palette is centralized in style.css `:root` custom properties; a theme is a
pure `:root` override block in static/themes/<name>.css that the server exposes
at the fixed /theme.css URL index.html links after style.css. The contract
under test: the configured theme's CSS is served verbatim; anything invalid —
unset, a non-slug name (the name is interpolated into a filesystem path), or a
missing file — degrades to EMPTY css with a 200, because the kiosk must never
lose the dashboard over a bad THEME value. Like test_static, every request uses
a bare `TestClient(app).get(...)` (no `with`) so the lifespan's network-touching
refresh loop never starts.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.config import settings
from app.main import _static_dir, app


def _get_theme_css() -> tuple[int, str, dict[str, str]]:
    resp = TestClient(app).get("/theme.css")
    return resp.status_code, resp.text, dict(resp.headers)


def test_default_is_empty_css() -> None:
    status, body, headers = _get_theme_css()
    assert status == 200
    assert body == ""
    assert headers["content-type"].startswith("text/css")
    # Same deploy-freshness contract as the static bundle: revalidate every load.
    assert headers["cache-control"] == "no-cache"


# Every theme we bundle. A new theme file isn't "shipped" until it's listed
# here (and in the README's theme table).
_BUNDLED_THEMES = ["nord", "gruvbox", "catppuccin", "synthwave"]


@pytest.mark.parametrize("name", _BUNDLED_THEMES)
def test_configured_theme_is_served_verbatim(
    monkeypatch: pytest.MonkeyPatch, name: str
) -> None:
    monkeypatch.setattr(settings, "theme", name)
    status, body, _ = _get_theme_css()
    assert status == 200
    assert body == (_static_dir / "themes" / f"{name}.css").read_text(encoding="utf-8")
    # Every theme overrides the :root palette. Hue-only themes stop there;
    # an effect theme (synthwave) may add documented effect rules on top —
    # see the contract note in nord.css.
    assert ":root {" in body


@pytest.mark.parametrize(
    "bad",
    [
        "no-such-theme",  # slug-shaped but the file doesn't exist
        "../style",  # path traversal out of themes/
        "themes/nord",  # separator smuggled inside a "name"
        "nord.css",  # the name contract is WITHOUT the extension
    ],
)
def test_invalid_theme_degrades_to_builtin(
    monkeypatch: pytest.MonkeyPatch, bad: str
) -> None:
    monkeypatch.setattr(settings, "theme", bad)
    status, body, _ = _get_theme_css()
    assert status == 200
    assert body == ""  # never a 4xx/5xx, and never someone else's file contents


def test_index_links_theme_after_style() -> None:
    # Cascade order is the whole mechanism: the theme's :root block only wins
    # because it loads after style.css.
    html = TestClient(app).get("/").text
    assert 'href="theme.css"' in html
    assert html.index('href="style.css"') < html.index('href="theme.css"')
