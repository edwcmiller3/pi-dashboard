"""HUD weather-glyph coverage + the no-ellipsis condition-wrap contract.

The HUD reuses the vendored weather-icons font for ALL 28 WMO conditions (it
consumes the server-resolved `icon` class rather than hand-drawing SVG). This
test proves the half a DOM-free JS test can't reach with the real WMO table:

  * every one of the 28 documented WMO codes - in BOTH day and night variants - 
    resolves via describe() to a wi-* class that is actually DEFINED in the
    vendored weather-icons.css (so it renders a real glyph on the kiosk, never
    tofu), with a non-empty condition label;
  * the HUD forecast row's condition text wraps rather than ellipsis-truncating
    (mock decision; worst case "Heavy freezing drizzle"), enforced in layout.css.

The companion static/layouts/hud/hud.test.js proves the renderer round-trips
each resolved `icon` onto its forecast row's .wi glyph - together they cover the
"all 28 codes render a non-tofu glyph + wrapped text in the HUD forecast" gate.
"""

from __future__ import annotations

import re
from pathlib import Path

from app.weather_codes import WMO, describe

_STATIC = Path(__file__).resolve().parent.parent / "static"
_WI_CSS = _STATIC / "vendor" / "weather-icons" / "weather-icons.css"
_HUD_CSS = _STATIC / "layouts" / "hud" / "layout.css"


def _defined_wi_classes() -> set[str]:
    """Every `.wi-*` class the vendored weather-icons stylesheet actually draws."""
    return set(re.findall(r"\.(wi-[a-z0-9-]+)::before", _WI_CSS.read_text()))


def test_all_28_wmo_codes_resolve_to_an_in_font_glyph() -> None:
    # Guard: the documented Open-Meteo table really is the full 28 interpretations.
    assert len(WMO) == 28
    classes = _defined_wi_classes()
    for code in WMO:
        for is_day in (True, False):
            cond = describe(code, is_day)
            icon = cond["icon"]
            assert icon.startswith("wi-"), f"code {code} icon is not a wi-* class"
            # Defined in the vendored CSS → the HUD renders a real glyph, not tofu.
            assert icon in classes, f"code {code} ({is_day=}) → {icon} not in weather-icons.css"
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
