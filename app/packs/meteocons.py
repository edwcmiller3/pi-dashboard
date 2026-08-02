"""The Meteocons icon packs: the semantic-name -> meteocons-drawing map and the
per-style stylesheet generators (flat / line / mono).

Pure, functional, no classes: one immutable name -> meteocons-name table plus
pure generators. Three visual packs (flat, line, mono) share this SINGLE map -
they differ only in which vendored SVG variant they paint and HOW they paint it
(background-image for flat/line, CSS mask + currentColor for mono), never in the
semantic -> drawing collapse. So the map lives here once and `pack_css(style)`
selects the style dir and painting technique.

The map is TOTAL over the union of `IconToken` (22 weather conditions, day/night
resolved by app.weather_codes.describe) and `GlyphName` (5 chrome glyphs: wind /
humidity / precip / sunrise / sunset) - 27 keys. Keys are typed
`IconToken | GlyphName`, so a name outside either Literal vocabulary fails mypy
rather than shipping a class no SVG backs; the values are meteocons asset names.

Richness note: the map preserves day/night wherever Meteocons has the drawing -
clear, mostly-clear, partly-cloudy, drizzle, rain, snow, showers and snow-showers
all carry day/night variants. A few tokens still collapse where Meteocons has no
distinct drawing: freezing-drizzle and freezing-rain both -> sleet (both neutral
tokens); the light/heavy intensity distinction is already dropped at the token
level in weather_codes.py, not here. Any collapse the icon can't show survives in
the contract `text` label. Every semantic name still gets its own `.wx-<name>`
class even when two share an SVG.

Offline discipline: every referenced SVG is vendored under
static/packs/meteocons/svg/{flat,line,mono}/ by tools/vendor_meteocons.py (a
dev-only one-shot); the generated CSS references them by ROOT-ABSOLUTE url(...)
(/packs/meteocons/svg/...), so the kiosk makes zero external network calls for
icons at runtime and the paths resolve regardless of whether the sheet is served
at the /pack.css route or loaded directly as a static file. The committed
static/packs/meteocons-<style>/pack.css must byte-match pack_css("<style>") (a
test asserts it); regenerate, never hand-edit.
"""

from __future__ import annotations

from types import MappingProxyType
from typing import Final, Literal, get_args

from app.packs.vocab import GlyphName
from app.weather_codes import IconToken

# The three visual styles. `mono` maps 1:1 to the local svg/mono dir (vendored
# from the CDN's "monochrome" style); flat/line keep their names.
Style = Literal["flat", "line", "mono"]

# How large to draw the SVG art inside its 1em box. Meteocons tiles carry a
# generous internal safe-area margin - the visible mark occupies only ~50-75% of
# its 128-unit canvas - so `contain` (which fits the WHOLE padded tile into the
# box) renders the glyph noticeably smaller than the weather-icons FONT pack,
# whose glyphs fill their em. Over-drawing the background to this factor consumes
# the tile padding so the visible glyph grows toward the font pack, without
# touching the box (layout sizing via font-size is unchanged). Applies to
# flat/line (background-size) and mono (mask-size) alike.
#
# Ceiling is empirical and set by the DENSEST tile: clear-day / sunrise / sunset
# fill ~75% of their canvas, so they clip above ~133% (0.75 * 1.33 = full box).
# 130% leaves a hair of margin below that, keeping EVERY icon clip-free while
# still lifting the glyphs well above `contain`. Do not raise without re-checking
# the densest tiles - a global factor is bounded by the fullest icon.
_ART_SCALE: Final = "130%"

# semantic name -> meteocons asset name. Total over `IconToken | GlyphName` (27
# keys). The right-hand side is the DISTINCT-drawing set the packs collapse onto
# (26 names); tools/vendor_meteocons.py vendors exactly those in each style dir.
_NAMES: Final[dict[IconToken | GlyphName, str]] = {
    # ── weather conditions (IconToken) ────────────────────────────────────────
    "clear-day": "clear-day",
    "clear-night": "clear-night",
    "mostly-clear-day": "mostly-clear-day",  # meteocons has a distinct "mostly" drawing
    "mostly-clear-night": "mostly-clear-night",  # as above, night
    "partly-cloudy-day": "partly-cloudy-day",
    "partly-cloudy-night": "partly-cloudy-night",
    "overcast": "overcast",
    "fog": "fog",
    "drizzle-day": "overcast-day-drizzle",  # steady drizzle: overcast sky, day
    "drizzle-night": "overcast-night-drizzle",  # as above, night
    "freezing-drizzle": "sleet",  # collapse: freezing precip -> sleet (neutral token)
    "rain-day": "overcast-day-rain",  # steady rain: overcast sky, day
    "rain-night": "overcast-night-rain",  # as above, night
    "freezing-rain": "sleet",  # collapse: freezing precip -> sleet (also freezing-drizzle)
    "snow-day": "overcast-day-snow",  # steady snow: overcast sky, day
    "snow-night": "overcast-night-snow",  # as above, night
    # Showers (WMO 80-86) keep the partly-cloudy framing, so steady precip
    # (overcast, above) reads visibly distinct from broken-cloud showers.
    "showers-day": "partly-cloudy-day-rain",
    "showers-night": "partly-cloudy-night-rain",
    "snow-showers-day": "partly-cloudy-day-snow",
    "snow-showers-night": "partly-cloudy-night-snow",
    "thunderstorm": "thunderstorms",
    "not-available": "not-available",
    # ── chrome / stat-tile glyphs (GlyphName) ─────────────────────────────────
    "wind": "windsock",
    "humidity": "humidity",
    "precip": "raindrop",
    "sunrise": "sunrise",
    "sunset": "sunset",
}

# Read-only view -> the table can't be mutated at runtime.
NAMES: Final = MappingProxyType(_NAMES)


def _svg_url(style: Style, meteocons_name: str) -> str:
    """Root-absolute url to the shared vendored svg root:
    /packs/meteocons/svg/<style>/<meteocons-name>.svg.

    The stylesheet is SERVED at the root route /pack.css, not at its on-disk
    path static/packs/meteocons-<style>/pack.css, so a relative url would
    resolve against / and 404. A root-absolute url resolves correctly whether
    the sheet is served via the /pack.css route or loaded directly as a static
    file, since the vendored SVGs are served at /packs/meteocons/svg/... either
    way. Static, no fetch beyond the one asset the browser already needs.
    """
    return f"/packs/meteocons/svg/{style}/{meteocons_name}.svg"


def _rule(style: Style, name: str, meteocons_name: str) -> str:
    """One `.wx-<name> { ... }` rule painting the vendored SVG.

    flat/line draw it as a background-image (the SVG carries its own color);
    mono uses it as a CSS mask over `currentColor`, so the glyph inherits the
    surrounding text color - static, no blur, no fetch.
    """
    url = _svg_url(style, meteocons_name)
    if style == "mono":
        return (
            f".wx-{name} {{ "
            f"-webkit-mask: url({url}) center/{_ART_SCALE} no-repeat; "
            f"mask: url({url}) center/{_ART_SCALE} no-repeat; "
            f"background-color: currentColor; }}"
        )
    return f".wx-{name} {{ background: url({url}) center/{_ART_SCALE} no-repeat; }}"


def pack_css(style: Style) -> str:
    """Generate a style's full stylesheet.

    Deterministic and total: a header, the shared `.wx-icon` base (sizing only -
    these are image/mask icons, no font-family), then one `.wx-<name>` rule for
    every `IconToken` (in vocabulary order) and every `GlyphName`. The committed
    static/packs/meteocons-<style>/pack.css must byte-match this output.
    """
    base = ".wx-icon {\n" + "  display: inline-block;\n  width: 1em;\n  height: 1em;\n" + "}\n"

    conditions = "\n".join(
        _rule(style, name, _NAMES[name]) for name in get_args(IconToken)
    )
    chrome = "\n".join(_rule(style, name, _NAMES[name]) for name in get_args(GlyphName))

    header = (
        "/*\n"
        f" * GENERATED by app/packs/meteocons.py pack_css(\"{style}\") - do NOT edit by hand.\n"
        f" * The Meteocons {style} pack stylesheet: the shared .wx-icon base plus one\n"
        " * .wx-<name> rule per semantic name (22 IconToken conditions + 5 GlyphName\n"
        " * chrome), each painting a vendored static SVG by root-absolute url(). SVGs\n"
        " * are served under /packs/meteocons/svg/ and vendored by tools/vendor_meteocons.py.\n"
        " * Regenerate on change, never hand-edit.\n"
        " */\n"
    )

    return (
        header
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
