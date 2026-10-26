"""The /theme.css palette-override route (THEME setting).

The configured theme's `:root` override is served verbatim; anything invalid
(unset, non-slug - the name becomes a filesystem path - or missing) degrades to
empty CSS with a 200, so a bad THEME never costs the kiosk its dashboard.
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
    assert headers["cache-control"] == "no-cache"


# A new theme isn't shipped until it's listed here (and in the README's table).
_BUNDLED_THEMES = ["nord", "gruvbox", "catppuccin", "synthwave"]


@pytest.mark.parametrize("name", _BUNDLED_THEMES)
def test_configured_theme_is_served_verbatim(
    monkeypatch: pytest.MonkeyPatch, name: str
) -> None:
    monkeypatch.setattr(settings, "theme", name)
    status, body, _ = _get_theme_css()
    assert status == 200
    assert body == (_static_dir / "themes" / f"{name}.css").read_text(encoding="utf-8")
    # Effect themes (synthwave) may add rules on top - see the note in nord.css.
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
    # The theme's :root block only wins because it loads after style.css.
    html = TestClient(app).get("/").text
    assert 'href="theme.css"' in html
    assert html.index('href="style.css"') < html.index('href="theme.css"')
