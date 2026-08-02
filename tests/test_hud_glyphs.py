"""HUD weather-condition coverage + the no-ellipsis condition-wrap contract.

The HUD consumes the server-resolved `icon` token (an icon pack maps it to a
glyph) rather than hand-drawing SVG. This test proves the half a DOM-free JS
test can't reach with the real WMO table:

  * every one of the 28 documented WMO codes - in BOTH day and night variants -
    resolves via describe() to a member of the IconToken vocabulary, with a
    non-empty condition label;
  * the HUD forecast row's condition text wraps rather than ellipsis-truncating
    (mock decision; worst case "Heavy freezing drizzle"), enforced in layout.css.

The font-subset / tofu guard (every emitted token maps to a real, in-font
glyph) now lives in the weather-icons pack test -
`tests/test_weather_icons_pack.py::test_every_pack_codepoint_is_in_the_vendored_woff2_subset`
- which owns the token -> glyph mapping and its generated CSS. Here we only check
the token vocabulary, which is all the transform now owns.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import get_args

from app.weather_codes import WMO, IconToken, describe

_STATIC = Path(__file__).resolve().parent.parent / "static"
_HUD_CSS = _STATIC / "layouts" / "hud" / "layout.css"


def test_all_28_wmo_codes_resolve_to_a_known_token() -> None:
    # Guard: the documented Open-Meteo table really is the full 28 interpretations.
    assert len(WMO) == 28
    tokens = set(get_args(IconToken))
    for code in WMO:
        for is_day in (True, False):
            cond = describe(code, is_day)
            icon = cond["icon"]
            # A member of the IconToken vocabulary -> an icon pack can resolve it.
            assert icon in tokens, f"code {code} ({is_day=}) -> {icon} not an IconToken"
            assert cond["text"].strip(), f"code {code} has an empty condition label"


def test_hud_condition_text_wraps_without_ellipsis() -> None:
    # The forecast row's condition cell must WRAP long strings to 2 lines, never
    # clip them with an ellipsis (mock decision log). Assert its CSS block does
    # not opt into single-line truncation.
    css = _HUD_CSS.read_text()
    match = re.search(r"\.hud \.frow \.cond\s*\{([^}]*)\}", css)
    assert match, "no `.hud .frow .cond` rule found in the HUD stylesheet"
    block = match.group(1)
    assert "text-overflow" not in block, ".cond must not set text-overflow (would truncate)"
    assert "nowrap" not in block, ".cond must not set white-space:nowrap (would prevent wrap)"
