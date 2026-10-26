"""HUD weather-condition coverage + the no-ellipsis condition-wrap contract.

Covers what the DOM-free JS tests can't reach with the real WMO table. The
token -> glyph tofu guard lives in tests/test_weather_icons_pack.py.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import get_args

from app.weather_codes import WMO, IconToken, describe

_STATIC = Path(__file__).resolve().parent.parent / "static"
_HUD_CSS = _STATIC / "layouts" / "hud" / "layout.css"


def test_all_28_wmo_codes_resolve_to_a_known_token() -> None:
    assert len(WMO) == 28
    tokens = set(get_args(IconToken))
    for code in WMO:
        for is_day in (True, False):
            cond = describe(code, is_day)
            icon = cond["icon"]
            assert icon in tokens, f"code {code} ({is_day=}) -> {icon} not an IconToken"
            assert cond["text"].strip(), f"code {code} has an empty condition label"


def test_hud_condition_text_wraps_without_ellipsis() -> None:
    # Long conditions ("Heavy freezing drizzle") wrap to 2 lines, never clip.
    css = _HUD_CSS.read_text()
    match = re.search(r"\.hud \.frow \.cond\s*\{([^}]*)\}", css)
    assert match, "no `.hud .frow .cond` rule found in the HUD stylesheet"
    block = match.group(1)
    assert "text-overflow" not in block, ".cond must not set text-overflow (would truncate)"
    assert "nowrap" not in block, ".cond must not set white-space:nowrap (would prevent wrap)"
