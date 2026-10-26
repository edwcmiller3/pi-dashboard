"""The layout-selection routes (LAYOUT setting): /layout.css and a generated
/layout.js re-exporting the selected layout's module.

Unlike a bad THEME (empty CSS = built-in palette), a bad LAYOUT fail-softs to
classic's module and CSS together: classic's DOM with empty CSS would render
unstyled, and an empty module would blank the kiosk.
"""

from __future__ import annotations

import logging

import pytest
from fastapi.testclient import TestClient

from app.config import settings
from app.main import _SLUG_RE, _static_dir, _warn_on_unknown_layout, app

# The fail-soft target and unset-LAYOUT default. "./layouts/..." resolves against
# /layout.js under the static mount.
_CLASSIC_LAYOUT_JS = 'export {layout} from "./layouts/classic/index.js";\n'


def _get(path: str) -> tuple[int, str, dict[str, str]]:
    resp = TestClient(app).get(path)
    return resp.status_code, resp.text, dict(resp.headers)


def _classic_css() -> str:
    return (_static_dir / "layouts" / "classic" / "layout.css").read_text(
        encoding="utf-8"
    )


def test_default_layout_is_classic() -> None:
    status, css, headers = _get("/layout.css")
    assert status == 200
    assert css == _classic_css()
    assert headers["content-type"].startswith("text/css")
    assert headers["cache-control"] == "no-cache"

    status, js, headers = _get("/layout.js")
    assert status == 200
    assert js == _CLASSIC_LAYOUT_JS
    # Strict ES-module loading silently refuses a wrong MIME, blanking the kiosk.
    assert headers["content-type"].startswith("text/javascript")
    assert headers["cache-control"] == "no-cache"


_BUNDLED_LAYOUTS = ["classic", "hud", "swiss-mono"]


@pytest.mark.parametrize("name", _BUNDLED_LAYOUTS)
def test_configured_layout_serves_its_css_and_module(
    monkeypatch: pytest.MonkeyPatch, name: str
) -> None:
    monkeypatch.setattr(settings, "layout", name)
    status, css, _ = _get("/layout.css")
    assert status == 200
    assert css == (_static_dir / "layouts" / name / "layout.css").read_text(
        encoding="utf-8"
    )

    status, js, headers = _get("/layout.js")
    assert status == 200
    assert js == f'export {{layout}} from "./layouts/{name}/index.js";\n'
    assert headers["content-type"].startswith("text/javascript")


def test_unset_layout_equals_explicit_classic(monkeypatch: pytest.MonkeyPatch) -> None:
    default_css = _get("/layout.css")[1]
    default_js = _get("/layout.js")[1]
    monkeypatch.setattr(settings, "layout", "classic")
    assert _get("/layout.css")[1] == default_css
    assert _get("/layout.js")[1] == default_js


@pytest.mark.parametrize(
    "bad",
    [
        "../classic",  # path traversal out of layouts/
        "layouts/classic",  # separator smuggled inside a "name"
        "classic/index",  # ditto
        "..",  # parent-dir traversal
        "classic.css",  # a dot is not slug-legal (the name is a bare dir name)
    ],
)
def test_invalid_layout_degrades_to_classic(
    monkeypatch: pytest.MonkeyPatch, bad: str
) -> None:
    monkeypatch.setattr(settings, "layout", bad)
    status, css, _ = _get("/layout.css")
    assert status == 200
    assert css == _classic_css()
    status, js, headers = _get("/layout.js")
    assert status == 200
    assert js == _CLASSIC_LAYOUT_JS
    assert headers["content-type"].startswith("text/javascript")


@pytest.mark.parametrize("ghost", ["ghost", "typo-but-sluglike"])
def test_valid_slug_but_absent_layout_falls_back_to_classic(
    monkeypatch: pytest.MonkeyPatch, ghost: str
) -> None:
    # A legal slug with no dir clears the regex, so existence must be checked:
    # re-exporting a missing index.js 404s the module graph at load time, which
    # app.js's try/catch can't catch.
    assert _SLUG_RE.fullmatch(ghost)
    assert not (_static_dir / "layouts" / ghost).exists()
    monkeypatch.setattr(settings, "layout", ghost)

    status, js, headers = _get("/layout.js")
    assert status == 200
    assert js == _CLASSIC_LAYOUT_JS
    assert headers["content-type"].startswith("text/javascript")

    status, css, _ = _get("/layout.css")
    assert status == 200
    assert css == _classic_css()


# macOS's case-insensitive filesystem let LAYOUT=HUD work in dev while the Pi
# silently fell back to classic; the routes fold case and .env whitespace first.
@pytest.mark.parametrize("name", ["HUD", "Hud", "hUd", " hud ", "hud\n"])
def test_layout_name_is_case_and_space_insensitive(
    monkeypatch: pytest.MonkeyPatch, name: str
) -> None:
    monkeypatch.setattr(settings, "layout", name)
    status, js, headers = _get("/layout.js")
    assert status == 200
    assert js == 'export {layout} from "./layouts/hud/index.js";\n'
    assert headers["content-type"].startswith("text/javascript")

    status, css, _ = _get("/layout.css")
    assert status == 200
    assert css == (_static_dir / "layouts" / "hud" / "layout.css").read_text(
        encoding="utf-8"
    )


def test_unknown_layout_warns_loudly_at_startup(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    # Per-request fail-soft is silent; this journal line is what explains "the
    # wall shows classic".
    monkeypatch.setattr(settings, "layout", "hudd")
    with caplog.at_level(logging.WARNING, logger="pi_dashboard.refresh"):
        _warn_on_unknown_layout()
    assert "hudd" in caplog.text
    assert "static/layouts" in caplog.text
    assert "hud" in caplog.text  # the "have: ..." list points at the real names


@pytest.mark.parametrize("resolvable", ["HUD", "classic", "", "swiss-mono"])
def test_resolvable_or_default_layout_is_silent_at_startup(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture, resolvable: str
) -> None:
    monkeypatch.setattr(settings, "layout", resolvable)
    with caplog.at_level(logging.WARNING, logger="pi_dashboard.refresh"):
        _warn_on_unknown_layout()
    assert "matches no layout" not in caplog.text


def test_index_loads_only_app_js_as_its_module() -> None:
    # A hardcoded layout module would silently bypass server-side selection.
    html = TestClient(app).get("/").text
    assert '<script type="module" src="app.js">' in html
    assert html.count('type="module"') == 1  # app.js is the sole module script
    assert "layouts/" not in html  # no classic/hud module or stylesheet hardcoded


def test_index_links_layout_between_style_and_theme() -> None:
    # Cascade: base < layout < theme, so a theme's :root block still wins.
    html = TestClient(app).get("/").text
    assert 'href="layout.css"' in html
    assert html.index('href="style.css"') < html.index('href="layout.css"')
    assert html.index('href="layout.css"') < html.index('href="theme.css"')


# ── admin skin routes ────────────────────────────────────────────────────────
# Same slug machinery and fail-soft as /layout.*: an unresolvable skin serves
# classic's, never a 404 that would strand the overlay.

_CLASSIC_ADMIN_JS = 'export {admin} from "./layouts/classic/admin.js";\n'


def _classic_admin_css() -> str:
    return (_static_dir / "layouts" / "classic" / "admin.css").read_text(
        encoding="utf-8"
    )


def _has_admin_skin(name: str) -> bool:
    return (_static_dir / "layouts" / name / "admin.js").is_file()


def test_default_admin_skin_is_classic() -> None:
    status, js, headers = _get("/admin.js")
    assert status == 200
    assert js == _CLASSIC_ADMIN_JS
    assert headers["content-type"].startswith("text/javascript")
    assert headers["cache-control"] == "no-cache"

    status, css, headers = _get("/admin.css")
    assert status == 200
    assert css == _classic_admin_css()
    assert headers["content-type"].startswith("text/css")
    assert headers["cache-control"] == "no-cache"


# Derived from disk so it stays true as layouts gain their own skins.
@pytest.mark.parametrize("name", _BUNDLED_LAYOUTS)
def test_layout_serves_its_admin_skin_or_classics(
    monkeypatch: pytest.MonkeyPatch, name: str
) -> None:
    monkeypatch.setattr(settings, "layout", name)
    skin = name if _has_admin_skin(name) else "classic"

    status, js, _ = _get("/admin.js")
    assert status == 200
    assert js == f'export {{admin}} from "./layouts/{skin}/admin.js";\n'

    status, css, _ = _get("/admin.css")
    assert status == 200
    assert css == (_static_dir / "layouts" / skin / "admin.css").read_text(
        encoding="utf-8"
    )


@pytest.mark.parametrize("bad", ["../classic", "layouts/classic", "..", "ghost"])
def test_unresolvable_layout_admin_skin_degrades_to_classic(
    monkeypatch: pytest.MonkeyPatch, bad: str
) -> None:
    monkeypatch.setattr(settings, "layout", bad)
    status, js, headers = _get("/admin.js")
    assert status == 200
    assert js == _CLASSIC_ADMIN_JS
    assert headers["content-type"].startswith("text/javascript")

    status, css, _ = _get("/admin.css")
    assert status == 200
    assert css == _classic_admin_css()


def test_admin_skin_name_is_case_and_space_insensitive(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "layout", " Classic\n")
    assert _get("/admin.js")[1] == _CLASSIC_ADMIN_JS


def test_layout_module_still_keys_off_index_js(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # _serve_module's leaf-filename param must not leak into /layout.js.
    monkeypatch.setattr(settings, "layout", "hud")
    assert _get("/layout.js")[1] == 'export {layout} from "./layouts/hud/index.js";\n'
