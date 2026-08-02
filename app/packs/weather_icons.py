"""The weather-icons reference icon pack: the semantic-name -> glyph map, its
generated stylesheet, and the exact codepoint subset the vendored font must ship.

Pure, functional, no classes: an immutable name -> codepoint table plus pure
generators. This module owns three things the frontend and the vendored font
depend on:

  * the mapping from each `IconToken` (weather condition, day/night-resolved by
    app.weather_codes.describe) and each `GlyphName` (chrome: wind / humidity /
    precip / sunrise / sunset) onto a concrete weather-icons PUA codepoint;
  * `pack_css()`, which generates the full stylesheet (self-hosted @font-face +
    the shared `.wx-icon` base + one `.wx-<name>::before` rule per name) served
    at /pack.css and committed to static/packs/weather-icons/pack.css;
  * `glyphs()`, the exact codepoint subset the pack requires: the pack test pins
    this set equal to the vendored weather-icons.woff2 cmap (no tofu, no dead
    weight). The woff2 was subset out-of-band - there is no in-repo subsetting
    step today.

Provenance of the codepoints: recovered from the ORIGINAL app/weather_codes.py
`_WMO` wi-* right-hand side at commit f13e0e1 (`git show`). The font collapses
several distinct conditions onto one drawing; those collapses are preserved
here EXACTLY as the font subset had them:

  * freezing-drizzle AND freezing-rain both -> wi-rain-mix (f017);
  * snow-showers-night -> the NEUTRAL wi-sleet (f0b5), not a wi-night-alt-*
    variant (the subset ships no wi-night-alt-sleet); snow-showers-day is
    wi-day-sleet (f0b2).

The five chrome codepoints (wind / humidity / precip / sunrise / sunset) lived
pre-refactor only in a test constant, not in code; they are declared here fresh.
The token distinction is preserved even where the font collapses it: two names
may share a codepoint, but each name still gets its own `.wx-<name>` class.
"""

from __future__ import annotations

from types import MappingProxyType
from typing import Final, get_args

from app.packs.vocab import GlyphName
from app.weather_codes import IconToken

# semantic name -> weather-icons PUA codepoint (bare hex, no leading backslash;
# `pack_css` adds the CSS `\` escape). Keys are typed `IconToken | GlyphName`, so
# a name outside either Literal vocabulary fails mypy rather than silently
# shipping a class no glyph backs. The trailing comment on each row is the
# original wi-* class this codepoint came from (the recovered ground truth).
_GLYPHS: Final[dict[IconToken | GlyphName, str]] = {
    # ── weather conditions (IconToken) ────────────────────────────────────────
    "clear-day": "f00d",  # wi-day-sunny
    "clear-night": "f02e",  # wi-night-clear
    "mostly-clear-day": "f00c",  # wi-day-sunny-overcast
    "mostly-clear-night": "f07e",  # wi-night-alt-cloudy-high
    "partly-cloudy-day": "f002",  # wi-day-cloudy
    "partly-cloudy-night": "f086",  # wi-night-alt-cloudy
    "overcast": "f013",  # wi-cloudy
    "fog": "f014",  # wi-fog
    "drizzle-day": "f00b",  # wi-day-sprinkle
    "drizzle-night": "f02b",  # wi-night-alt-sprinkle
    "freezing-drizzle": "f017",  # wi-rain-mix (collapse: also freezing-rain)
    "rain-day": "f008",  # wi-day-rain
    "rain-night": "f028",  # wi-night-alt-rain
    "freezing-rain": "f017",  # wi-rain-mix (collapse: also freezing-drizzle)
    "snow-day": "f00a",  # wi-day-snow
    "snow-night": "f02a",  # wi-night-alt-snow
    "showers-day": "f009",  # wi-day-showers
    "showers-night": "f029",  # wi-night-alt-showers
    "snow-showers-day": "f0b2",  # wi-day-sleet
    "snow-showers-night": "f0b5",  # wi-sleet (neutral - no night-alt in subset)
    "thunderstorm": "f01e",  # wi-thunderstorm
    "not-available": "f07b",  # wi-na
    # ── chrome / stat-tile glyphs (GlyphName) ─────────────────────────────────
    "wind": "f050",  # wi-strong-wind
    "humidity": "f07a",  # wi-humidity
    "precip": "f078",  # wi-raindrop
    "sunrise": "f051",  # wi-sunrise
    "sunset": "f052",  # wi-sunset
}

# Read-only view -> the table can't be mutated at runtime.
GLYPHS: Final = MappingProxyType(_GLYPHS)

# The self-hosted subset font. The url is RELATIVE to this pack's on-disk home
# (static/packs/weather-icons/) back to the shared vendor dir, so the committed
# pack.css resolves the woff2 both as a file and via the /pack.css route.
_FONT_FAMILY: Final = "weathericons"
_WOFF2_URL: Final = "../../vendor/weather-icons/weather-icons.woff2"

# The shared base class every layout's sizing/color selectors target. Its
# declarations are copied VERBATIM from the vendored `.wi` rule
# (weather-icons.css) - only the class name changes (.wi -> .wx-icon).
_BASE_DECLS: Final[tuple[str, ...]] = (
    "display: inline-block",
    f"font-family: {_FONT_FAMILY}",
    "font-style: normal",
    "font-weight: 400",
    "line-height: 1",
    "-webkit-font-smoothing: antialiased",
    "-moz-osx-font-smoothing: grayscale",
)


def glyphs() -> frozenset[str]:
    """Every PUA codepoint (bare hex) the pack renders - conditions AND chrome.

    Defines the exact codepoint subset the pack requires: the pack test
    (tests/test_weather_icons_pack.py) asserts this set equals the cmap of the
    vendored static/vendor/weather-icons/weather-icons.woff2, both directions - no
    tofu (missing glyph) and no dead weight (extra unused glyph). The woff2 was
    subset out-of-band; there is no in-repo subsetting step today (a future
    tools/vendor_weather_icons.py could consume this set, but none exists yet).
    Collapsed names share a codepoint, so this is the DISTINCT set (26), not one
    per name (27).
    """
    return frozenset(_GLYPHS.values())


def _rule(name: str, codepoint: str) -> str:
    """One `.wx-<name>::before { content: "\\fXXXX"; }` rule."""
    return f'.wx-{name}::before {{ content: "\\{codepoint}"; }}'


def pack_css() -> str:
    """Generate the pack's full stylesheet.

    Deterministic and total: the @font-face, the shared `.wx-icon` base, then one
    `.wx-<name>::before` rule for every `IconToken` (in vocabulary order) and
    every `GlyphName`. The committed static/packs/weather-icons/pack.css must
    byte-match this output (a test asserts it); regenerate, never hand-edit.
    """
    face = (
        "@font-face {\n"
        f"  font-family: {_FONT_FAMILY};\n"
        f'  src: url({_WOFF2_URL}) format("woff2");\n'
        "  font-weight: 400;\n"
        "  font-style: normal;\n"
        "  font-display: block;\n"
        "}\n"
    )
    base = ".wx-icon {\n" + "".join(f"  {d};\n" for d in _BASE_DECLS) + "}\n"

    conditions = "\n".join(_rule(name, _GLYPHS[name]) for name in get_args(IconToken))
    chrome = "\n".join(_rule(name, _GLYPHS[name]) for name in get_args(GlyphName))

    header = (
        "/*\n"
        " * GENERATED by app/packs/weather_icons.py pack_css() - do NOT edit by hand.\n"
        " * The weather-icons reference pack stylesheet: a self-hosted subset font,\n"
        " * the shared .wx-icon base, and one .wx-<name>::before rule per semantic\n"
        " * name (22 IconToken conditions + 5 GlyphName chrome). Regenerate on change.\n"
        " */\n"
    )

    return (
        header
        + "\n"
        + face
        + "\n"
        + base
        + "\n"
        + "/* Weather condition glyphs (IconToken) - resolved by describe(). */\n"
        + conditions
        + "\n\n"
        + "/* Chrome / stat-tile glyphs (GlyphName): wind / humidity / precip / sunrise / sunset. */\n"
        + chrome
        + "\n"
    )
