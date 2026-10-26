"""The icon-pack-selection routes (ICON_PACK setting), mirroring /layout.*
(see test_layout.py for the shared fail-soft reasoning).

A bad ICON_PACK fail-softs to weather-icons' module and CSS together - the
module with empty icon CSS would render the icons unstyled.
"""

from __future__ import annotations

import re
from urllib.parse import urljoin

import pytest
from fastapi.testclient import TestClient

from app.config import settings
from app.main import _SLUG_RE, _static_dir, app

# The fail-soft target and unset-ICON_PACK default.
_WEATHER_ICONS_PACK_JS = 'export {iconPack} from "./packs/weather-icons/index.js";\n'


def _get(path: str) -> tuple[int, str, dict[str, str]]:
    resp = TestClient(app).get(path)
    return resp.status_code, resp.text, dict(resp.headers)


def _weather_icons_css() -> str:
    return (_static_dir / "packs" / "weather-icons" / "pack.css").read_text(
        encoding="utf-8"
    )


def test_default_pack_is_weather_icons() -> None:
    status, css, headers = _get("/pack.css")
    assert status == 200
    assert css == _weather_icons_css()
    # The real sheet, not the empty last-resort body.
    assert ".wx-icon {" in css
    assert ".wx-clear-day::before" in css
    assert headers["content-type"].startswith("text/css")
    assert headers["cache-control"] == "no-cache"

    status, js, headers = _get("/pack.js")
    assert status == 200
    assert js == _WEATHER_ICONS_PACK_JS
    assert headers["content-type"].startswith("text/javascript")
    assert headers["cache-control"] == "no-cache"


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
    status, css, _ = _get("/pack.css")
    assert status == 200
    assert css == _weather_icons_css()
    status, js, headers = _get("/pack.js")
    assert status == 200
    assert js == _WEATHER_ICONS_PACK_JS
    assert headers["content-type"].startswith("text/javascript")


@pytest.mark.parametrize("ghost", ["no-such-pack", "typo-but-sluglike"])
def test_valid_slug_but_absent_pack_falls_back_to_weather_icons(
    monkeypatch: pytest.MonkeyPatch, ghost: str
) -> None:
    assert _SLUG_RE.fullmatch(ghost)
    assert not (_static_dir / "packs" / ghost).exists()
    monkeypatch.setattr(settings, "icon_pack", ghost)

    status, js, headers = _get("/pack.js")
    assert status == 200
    assert js == _WEATHER_ICONS_PACK_JS
    assert headers["content-type"].startswith("text/javascript")

    status, css, _ = _get("/pack.css")
    assert status == 200
    assert css == _weather_icons_css()


# The same case-insensitive-macOS trap as layouts. Uses a non-default pack so a
# mis-fold (which fail-softs to weather-icons) can't pass.
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


# The payload of each url(...), minus optional quotes.
_URL_RE = re.compile(r"""url\(\s*['"]?([^'")]+?)['"]?\s*\)""")


@pytest.mark.parametrize("name", _BUNDLED_PACKS)
def test_served_css_url_references_all_resolve_to_200(
    monkeypatch: pytest.MonkeyPatch, name: str
) -> None:
    # Resolve each url() against the /pack.css route, as a browser does, not the
    # on-disk path - the only check that catches a route-vs-disk mismatch (a
    # relative url() resolves against / and 404s).
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
