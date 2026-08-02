"""The icon-pack-selection routes (ICON_PACK setting), mirroring /layout.*.

An icon pack is a directory under static/packs/ whose index.js + pack.css the
server exposes at two fixed URLs: GET /pack.css serves the stylesheet and GET
/pack.js returns a GENERATED one-line ES module re-exporting the selected pack
so app.js picks it up with no fetch race and no HTML templating.

This clones test_layout.py's STRUCTURE for the pack axis - parametrized
valid/invalid inputs (incl. path traversal), a bare `TestClient(app).get(...)`
(no `with`) so the lifespan's network-touching refresh loop never starts, and
degrade-to-default - but pivoted from LAYOUT->ICON_PACK and classic->
weather-icons. A pack is BOTH a module and a stylesheet, so a bad ICON_PACK
fail-softs to the whole weather-icons EXPERIENCE - its module AND its CSS - not
to empty CSS: serving the weather-icons module with empty icon CSS would render
the icons unstyled. ICON_PACK defaults to "weather-icons", so an unset ICON_PACK
and ICON_PACK=weather-icons must serve the identical built-in experience.
"""

from __future__ import annotations

import re
from urllib.parse import urljoin

import pytest
from fastapi.testclient import TestClient

from app.config import settings
from app.main import _SLUG_RE, _static_dir, app

# The generated module body for the weather-icons pack - the fail-soft target and
# the unset-ICON_PACK default. Note the relative "./packs/..." specifier: it
# resolves against /pack.js under the static mount → /packs/weather-icons/index.js.
_WEATHER_ICONS_PACK_JS = 'export {iconPack} from "./packs/weather-icons/index.js";\n'


def _get(path: str) -> tuple[int, str, dict[str, str]]:
    resp = TestClient(app).get(path)
    return resp.status_code, resp.text, dict(resp.headers)


def _weather_icons_css() -> str:
    return (_static_dir / "packs" / "weather-icons" / "pack.css").read_text(
        encoding="utf-8"
    )


def test_default_pack_is_weather_icons() -> None:
    # settings.icon_pack defaults to "weather-icons" (unset ICON_PACK) - no monkeypatch.
    status, css, headers = _get("/pack.css")
    assert status == 200
    assert css == _weather_icons_css()
    # The real pack stylesheet, not the empty last-resort body: its base rule and a
    # condition glyph rule both survive (proves it's the actual weather-icons sheet).
    assert ".wx-icon {" in css
    assert ".wx-clear-day::before" in css
    assert headers["content-type"].startswith("text/css")
    # Same deploy-freshness contract as the static bundle: revalidate every load.
    assert headers["cache-control"] == "no-cache"

    status, js, headers = _get("/pack.js")
    assert status == 200
    assert js == _WEATHER_ICONS_PACK_JS
    # A wrong JS MIME is SILENTLY refused under strict ES-module loading, which
    # would blank the kiosk - pin the correct type explicitly.
    assert headers["content-type"].startswith("text/javascript")
    assert headers["cache-control"] == "no-cache"


# Every icon pack selectable today: the built-in weather-icons reference pack plus
# the three meteocons variants, each an index.js + pack.css under static/packs/
# <name>/. Appended one line at a time, exactly like _BUNDLED_LAYOUTS.
_BUNDLED_PACKS = ["weather-icons", "meteocons-flat", "meteocons-line", "meteocons-mono"]


@pytest.mark.parametrize("name", _BUNDLED_PACKS)
def test_configured_pack_serves_its_css_and_module(
    monkeypatch: pytest.MonkeyPatch, name: str
) -> None:
    monkeypatch.setattr(settings, "icon_pack", name)
    status, css, _ = _get("/pack.css")
    assert status == 200
    assert css == (_static_dir / "packs" / name / "pack.css").read_text(
        encoding="utf-8"
    )

    status, js, headers = _get("/pack.js")
    assert status == 200
    assert js == f'export {{iconPack}} from "./packs/{name}/index.js";\n'
    assert headers["content-type"].startswith("text/javascript")


def test_unset_pack_equals_explicit_weather_icons(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # An unset ICON_PACK and ICON_PACK=weather-icons serve byte-identical CSS +
    # module bodies (the built-in-pack default equivalence).
    default_css = _get("/pack.css")[1]
    default_js = _get("/pack.js")[1]
    monkeypatch.setattr(settings, "icon_pack", "weather-icons")
    assert _get("/pack.css")[1] == default_css
    assert _get("/pack.js")[1] == default_js


@pytest.mark.parametrize(
    "bad",
    [
        "../weather-icons",  # path traversal out of packs/
        "packs/weather-icons",  # separator smuggled inside a "name"
        "weather-icons/index",  # ditto
        "..",  # parent-dir traversal
        "weather-icons.css",  # a dot is not slug-legal (the name is a bare dir name)
    ],
)
def test_invalid_pack_degrades_to_weather_icons(
    monkeypatch: pytest.MonkeyPatch, bad: str
) -> None:
    monkeypatch.setattr(settings, "icon_pack", bad)
    # CSS: fail-softs to the weather-icons stylesheet (NOT empty) so the icons the
    # module fallback serves keep their styling - never a 4xx/5xx, and never
    # someone else's file contents smuggled out via traversal.
    status, css, _ = _get("/pack.css")
    assert status == 200
    assert css == _weather_icons_css()
    # Module: a pack SELECTS a module (not a served stylesheet), so its fail-soft is
    # the weather-icons re-export, not an empty body - otherwise app.js's
    # `import {iconPack}` would resolve to nothing and blank the kiosk.
    status, js, headers = _get("/pack.js")
    assert status == 200
    assert js == _WEATHER_ICONS_PACK_JS
    assert headers["content-type"].startswith("text/javascript")


@pytest.mark.parametrize("ghost", ["no-such-pack", "typo-but-sluglike"])
def test_valid_slug_but_absent_pack_falls_back_to_weather_icons(
    monkeypatch: pytest.MonkeyPatch, ghost: str
) -> None:
    # Distinct from the bad-slug/traversal case: `ghost` IS a legal slug, so it
    # clears the regex - but no static/packs/<ghost>/ dir exists. Both the module
    # and the CSS must fail-soft to the weather-icons experience, coherently.
    assert _SLUG_RE.fullmatch(ghost)  # guard: really is a legal slug
    assert not (_static_dir / "packs" / ghost).exists()
    monkeypatch.setattr(settings, "icon_pack", ghost)

    # Module: emitting a re-export of the missing index.js would 404 the ES-module
    # graph at LOAD time (which app.js's usage-level try/catch cannot catch → blank
    # kiosk), so /pack.js verifies existence and falls back to weather-icons.
    status, js, headers = _get("/pack.js")
    assert status == 200
    assert js == _WEATHER_ICONS_PACK_JS  # weather-icons, NOT a re-export of the missing module
    assert headers["content-type"].startswith("text/javascript")

    # CSS: the absent static/packs/<ghost>/pack.css must degrade to the
    # weather-icons stylesheet (NOT empty), matching the module fallback -
    # otherwise the served icons would render with no styling.
    status, css, _ = _get("/pack.css")
    assert status == 200
    assert css == _weather_icons_css()


# The same dev/prod parity trap the layout routes fold away: the Mac's filesystem
# is case-INSENSITIVE so ICON_PACK=Meteocons-Flat "works" in dev, but the Pi's is
# case-SENSITIVE so packs/Meteocons-Flat/ doesn't exist there and it silently falls
# back. The routes fold case (and stray .env whitespace) before touching disk, so
# every variant of a real pack resolves to the same asset on either filesystem.
# Pointed at meteocons-flat, a NON-default pack, so a correct fold resolves to the
# meteocons-flat assets - visibly DISTINCT from the weather-icons experience a
# mis-fold would fail-soft to, which folding at weather-icons could not have shown.
@pytest.mark.parametrize(
    "name",
    ["METEOCONS-FLAT", "Meteocons-Flat", "meteocons-FLAT", " meteocons-flat ", "meteocons-flat\n"],
)
def test_pack_name_is_case_and_space_insensitive(
    monkeypatch: pytest.MonkeyPatch, name: str
) -> None:
    monkeypatch.setattr(settings, "icon_pack", name)
    status, js, headers = _get("/pack.js")
    assert status == 200
    assert js == 'export {iconPack} from "./packs/meteocons-flat/index.js";\n'
    assert headers["content-type"].startswith("text/javascript")

    status, css, _ = _get("/pack.css")
    assert status == 200
    assert css == (_static_dir / "packs" / "meteocons-flat" / "pack.css").read_text(
        encoding="utf-8"
    )


# Matches the payload of every url(...) in a stylesheet, stripping optional single
# or double quotes around the reference.
_URL_RE = re.compile(r"""url\(\s*['"]?([^'")]+?)['"]?\s*\)""")


@pytest.mark.parametrize("name", _BUNDLED_PACKS)
def test_served_css_url_references_all_resolve_to_200(
    monkeypatch: pytest.MonkeyPatch, name: str
) -> None:
    # The guard the suite lacked: every asset url() in the SERVED /pack.css must
    # resolve to a real 200 when the browser resolves it against the /pack.css
    # route path. A relative url() would resolve against / and 404 (the meteocons
    # bug), so resolving each ref the way a browser does - urljoin against the
    # ROUTE, not the on-disk file - and re-fetching it through the app is the only
    # check that catches a route-vs-disk path mismatch in any pack.
    monkeypatch.setattr(settings, "icon_pack", name)
    status, css, _ = _get("/pack.css")
    assert status == 200

    refs = _URL_RE.findall(css)
    assert refs, f"pack {name!r} served no url() references to check"
    for raw in refs:
        resolved = urljoin("/pack.css", raw)
        asset_status, _, _ = _get(resolved)
        assert asset_status == 200, (
            f"pack {name!r}: url({raw!r}) resolved to {resolved!r} -> "
            f"HTTP {asset_status} (browser would 404 this asset)"
        )
