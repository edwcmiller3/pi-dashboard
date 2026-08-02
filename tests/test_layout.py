"""The layout-selection routes (LAYOUT setting), mirroring the theme mechanism.

A layout is a directory under static/layouts/ whose index.js + layout.css the
server exposes at two fixed URLs: GET /layout.css serves the stylesheet (linked
between style.css and theme.css so the cascade is base < layout < theme), and
GET /layout.js returns a GENERATED one-line ES module re-exporting the selected
layout so app.js picks it up with no fetch race and no HTML templating.

This borrows test_theme.py's STRUCTURE - parametrized valid/invalid inputs
(incl. path traversal), a bare `TestClient(app).get(...)` (no `with`) so the
lifespan's network-touching refresh loop never starts, and degrade-to-default - 
but not its assertions 1:1: a layout is BOTH a module and a stylesheet, so a bad
LAYOUT fail-softs to the whole classic EXPERIENCE - classic's module AND
classic's CSS - not to empty CSS the way a bad THEME does (a theme is a pure
palette override, so empty correctly means "built-in palette"). The two
fail-softs must stay coherent: serving classic's DOM+logic (module) with empty
region CSS would render the classic layout unstyled. LAYOUT defaults to
"classic", so an unset LAYOUT and LAYOUT=classic must serve the identical
classic experience (the plan's Phase-2 exit criterion).
"""

from __future__ import annotations

import logging

import pytest
from fastapi.testclient import TestClient

from app.config import settings
from app.main import _SLUG_RE, _static_dir, _warn_on_unknown_layout, app

# The generated module body for the classic layout - the fail-soft target and
# the unset-LAYOUT default. Note the relative "./layouts/..." specifier: it
# resolves against /layout.js under the static mount → /layouts/classic/index.js.
_CLASSIC_LAYOUT_JS = 'export {layout} from "./layouts/classic/index.js";\n'


def _get(path: str) -> tuple[int, str, dict[str, str]]:
    resp = TestClient(app).get(path)
    return resp.status_code, resp.text, dict(resp.headers)


def _classic_css() -> str:
    return (_static_dir / "layouts" / "classic" / "layout.css").read_text(
        encoding="utf-8"
    )


def test_default_layout_is_classic() -> None:
    # settings.layout defaults to "classic" (unset LAYOUT) - no monkeypatch.
    status, css, headers = _get("/layout.css")
    assert status == 200
    assert css == _classic_css()
    assert headers["content-type"].startswith("text/css")
    # Same deploy-freshness contract as the static bundle: revalidate every load.
    assert headers["cache-control"] == "no-cache"

    status, js, headers = _get("/layout.js")
    assert status == 200
    assert js == _CLASSIC_LAYOUT_JS
    # A wrong JS MIME is SILENTLY refused under strict ES-module loading, which
    # would blank the kiosk - pin the correct type explicitly.
    assert headers["content-type"].startswith("text/javascript")
    assert headers["cache-control"] == "no-cache"


# Every layout selectable today: classic (the production UI), hud (the
# instrument-HUD, Phase 3), and swiss-mono (the swiss-grotesque paper design) - 
# each an index.js + layout.css under static/layouts/<name>/.
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
    # The equivalence the plan pins as Phase 2's exit criterion: unset LAYOUT and
    # LAYOUT=classic serve byte-identical CSS + module bodies.
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
    # CSS: fail-softs to classic's stylesheet (NOT empty, unlike a bad theme) so
    # the classic DOM the module fallback serves keeps its region styling - never
    # a 4xx/5xx, and never someone else's file contents smuggled out via traversal.
    status, css, _ = _get("/layout.css")
    assert status == 200
    assert css == _classic_css()
    # Module: a layout SELECTS a module (not a served stylesheet), so its
    # fail-soft is the classic re-export, not an empty body - otherwise app.js's
    # `import {layout}` would resolve to nothing and blank the kiosk.
    status, js, headers = _get("/layout.js")
    assert status == 200
    assert js == _CLASSIC_LAYOUT_JS
    assert headers["content-type"].startswith("text/javascript")


@pytest.mark.parametrize("ghost", ["ghost", "typo-but-sluglike"])
def test_valid_slug_but_absent_layout_falls_back_to_classic(
    monkeypatch: pytest.MonkeyPatch, ghost: str
) -> None:
    # Distinct from the bad-slug/traversal case: `ghost` IS a legal slug, so it
    # clears the regex - but no static/layouts/<ghost>/ dir exists. Both the
    # module and the CSS must fail-soft to the classic experience, coherently.
    assert _SLUG_RE.fullmatch(ghost)  # guard: really is a legal slug
    assert not (_static_dir / "layouts" / ghost).exists()
    monkeypatch.setattr(settings, "layout", ghost)

    # Module: emitting a re-export of the missing index.js would 404 the
    # ES-module graph at LOAD time (which app.js's usage-level try/catch cannot
    # catch → blank kiosk), so /layout.js verifies existence and falls back to
    # classic, not just to a valid name.
    status, js, headers = _get("/layout.js")
    assert status == 200
    assert js == _CLASSIC_LAYOUT_JS  # classic, NOT a re-export of the missing module
    assert headers["content-type"].startswith("text/javascript")

    # CSS: the absent static/layouts/<ghost>/layout.css must degrade to classic's
    # stylesheet (NOT empty), matching the module fallback - otherwise the served
    # classic DOM would render with no region styling.
    status, css, _ = _get("/layout.css")
    assert status == 200
    assert css == _classic_css()


# The dev/prod parity trap that shipped: the Mac's filesystem is case-INSENSITIVE
# so LAYOUT=HUD "worked" in dev, but the Pi's is case-SENSITIVE so layouts/HUD/
# didn't exist there and it silently fell back to classic. The routes now fold
# case (and stray .env whitespace) before touching disk, so every variant of a
# real layout resolves to the same asset on either filesystem.
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
    # A valid-slug-but-absent LAYOUT must be SURFACED at boot (not just fail-soft
    # silently per request), naming the value and the layouts that DO exist - the
    # journal line that turns "the wall shows classic" from a mystery into a
    # 10-second diagnosis.
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
    # The startup check must NOT cry wolf: a case variant that resolves (HUD->hud),
    # the explicit/implicit classic default, and a real layout all stay quiet.
    monkeypatch.setattr(settings, "layout", resolvable)
    with caplog.at_level(logging.WARNING, logger="pi_dashboard.refresh"):
        _warn_on_unknown_layout()
    assert "matches no layout" not in caplog.text


def test_index_loads_only_app_js_as_its_module() -> None:
    # No existing test asserts WHICH modules index.html loads (test_theme checks
    # stylesheet link order only). The layout must arrive via the /layout.js
    # route through app.js - index.html must NOT hardcode a concrete layout
    # module, or server-side layout selection is silently bypassed.
    html = TestClient(app).get("/").text
    assert '<script type="module" src="app.js">' in html
    assert html.count('type="module"') == 1  # app.js is the sole module script
    assert "layouts/" not in html  # no classic/hud module or stylesheet hardcoded


def test_index_links_layout_between_style_and_theme() -> None:
    # Cascade order is the whole mechanism: base < layout < theme. The layout's
    # rules must load after style.css (so it can extend the base) and before
    # theme.css (so a theme's :root block still wins).
    html = TestClient(app).get("/").text
    assert 'href="layout.css"' in html
    assert html.index('href="style.css"') < html.index('href="layout.css"')
    assert html.index('href="layout.css"') < html.index('href="theme.css"')
