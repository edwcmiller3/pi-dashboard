"""Tests for the weather-icons reference pack: its generated stylesheet and the
font-subset it drives.

The pack (app/packs/weather_icons.py) is now the single source of truth for the
vendored weather-icons font subset, taking over the tofu guard that used to live
in tests/test_weather_codes.py (glyphs() == ALLOWED_GLYPHS). Three properties:

  * completeness - the `_GLYPHS` map keys are EXACTLY the union vocabulary, and
    every IconToken AND every GlyphName gets a `.wx-<name>::before` rule in the
    generated CSS (nothing the frontend can request is unstyled, no stray key);
  * generator-matches-disk - `pack_css()` equals the committed pack.css byte for
    byte (so the served/on-disk stylesheet can't drift from the generator);
  * two-way woff2 pin - the vendored subset's cmap is EXACTLY the codepoints the
    pack references: no missing glyph (tofu on the kiosk) AND no extra unused
    glyph (dead weight shipped in the font).

The tofu guard reuses tests/test_hud_fonts.py's woff2-introspection approach
(fontTools TTFont(...).getBestCmap()) rather than inventing a new one.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import get_args

from fontTools.ttLib import TTFont

from app.packs.vocab import GlyphName
from app.packs.weather_icons import GLYPHS, glyphs, pack_css
from app.weather_codes import IconToken

_STATIC = Path(__file__).resolve().parent.parent / "static"
_PACK_CSS = _STATIC / "packs" / "weather-icons" / "pack.css"
_WOFF2 = _STATIC / "vendor" / "weather-icons" / "weather-icons.woff2"


def _rule_names(css: str) -> set[str]:
    """Every `<name>` with a `.wx-<name>::before` rule in the CSS."""
    return set(re.findall(r"\.wx-([a-z0-9-]+)::before", css))


def _css_codepoints(css: str) -> set[int]:
    """Every codepoint (as int) referenced by a `content: "\\fXXXX"` declaration."""
    return {int(h, 16) for h in re.findall(r'content:\s*"\\([0-9a-fA-F]+)"', css)}


def _cmap(path: Path) -> set[int]:
    # Mirrors tests/test_hud_fonts.py::_cmap - the codepoints the subset ships.
    return set(TTFont(path).getBestCmap().keys())


def test_glyphs_map_is_complete_over_the_union_vocabulary() -> None:
    # Total over IconToken | GlyphName: the map keys are EXACTLY the union
    # vocabulary, so a stray / typo'd / extra _GLYPHS key is caught by a test, not
    # only by mypy (mirrors tests/test_meteocons_pack.py's NAMES completeness pin).
    assert set(GLYPHS) == set(get_args(IconToken)) | set(get_args(GlyphName))
    assert len(GLYPHS) == 27  # 22 conditions + 5 chrome (distinct keys, collapses share a codepoint)


def test_every_icontoken_has_a_rule() -> None:
    names = _rule_names(pack_css())
    for token in get_args(IconToken):
        assert token in names, f"IconToken {token!r} has no .wx-{token}::before rule"


def test_every_glyphname_has_a_rule() -> None:
    names = _rule_names(pack_css())
    for name in get_args(GlyphName):
        assert name in names, f"GlyphName {name!r} has no .wx-{name}::before rule"


def test_pack_css_rules_are_exactly_the_27_names() -> None:
    # No dead rules, no missing ones: the CSS styles precisely the union vocabulary.
    expected = set(get_args(IconToken)) | set(get_args(GlyphName))
    assert _rule_names(pack_css()) == expected
    assert len(expected) == 27  # 22 conditions + 5 chrome


def test_generated_css_matches_committed_disk_file() -> None:
    # The committed pack.css (served at /pack.css, linked by index.html) must be
    # exactly what the generator emits - regenerate on change, never hand-edit.
    assert pack_css() == _PACK_CSS.read_text(encoding="utf-8")


def test_glyphs_are_the_distinct_codepoints_the_css_references() -> None:
    # glyphs() (the font-subset driver) and the generated CSS agree on the exact
    # set of codepoints, so subsetting off glyphs() can't diverge from what the
    # stylesheet asks the font to draw. Distinct because collapsed names share a
    # codepoint (freezing-drizzle + freezing-rain; snow-showers-night reuses sleet).
    assert {int(cp, 16) for cp in glyphs()} == _css_codepoints(pack_css())


def test_woff2_subset_cmap_is_exactly_the_pack_codepoints() -> None:
    # Two-way pin (restores the old glyphs() == ALLOWED_GLYPHS direction; mirrors
    # tests/test_hud_fonts.py's `_cmap(...) == EXPECTED_CPS`): the vendored subset
    # ships EXACTLY the codepoints the pack references. The subset-only check let a
    # bloated / un-subset woff2 pass; this catches BOTH directions.
    cmap = _cmap(_WOFF2)
    referenced = _css_codepoints(pack_css())
    missing = referenced - cmap  # a referenced glyph absent from the woff2 -> tofu
    extra = cmap - referenced  # a shipped glyph nothing references -> dead weight
    assert not missing, f"woff2 subset is MISSING {sorted(f'U+{c:04X}' for c in missing)} (tofu)"
    assert not extra, f"woff2 subset ships UNUSED {sorted(f'U+{c:04X}' for c in extra)} (dead weight)"
    assert cmap == referenced
