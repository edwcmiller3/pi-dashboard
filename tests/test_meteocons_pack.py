"""Tests for the Meteocons packs: the shared semantic -> drawing map, the
vendored SVG subset it drives, and the three generated stylesheets.

The one map (app/packs/meteocons.py) feeds three visual packs (flat / line /
mono). Four properties:

  * completeness - every IconToken AND every GlyphName maps to a meteocons name
    (nothing the frontend can request is unmapped);
  * offline subset - every mapped meteocons name exists as a vendored SVG file in
    EACH of the three style dirs (no runtime fetch, no missing asset on the kiosk);
  * generator-matches-disk - each pack_css(style) equals the committed
    static/packs/meteocons-<style>/pack.css byte for byte (served CSS can't drift);
  * rule vocabulary - the CSS styles precisely the 27-name union (no dead / missing
    rules).
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import get_args

from app.packs.meteocons import NAMES, Style, pack_css
from app.packs.vocab import GlyphName
from app.weather_codes import IconToken

_STATIC = Path(__file__).resolve().parent.parent / "static"
_SVG_ROOT = _STATIC / "packs" / "meteocons" / "svg"
_STYLES: tuple[Style, ...] = ("flat", "line", "mono")


def _rule_names(css: str) -> set[str]:
    """Every `<name>` with a `.wx-<name> {` rule in the CSS (excludes .wx-icon)."""
    return set(re.findall(r"\.wx-([a-z0-9-]+) \{", css)) - {"icon"}


def test_map_is_complete_over_the_union_vocabulary() -> None:
    # Total over IconToken | GlyphName: every semantic name the frontend can ask
    # for resolves to a meteocons drawing.
    for token in get_args(IconToken):
        assert token in NAMES, f"IconToken {token!r} is unmapped"
    for name in get_args(GlyphName):
        assert name in NAMES, f"GlyphName {name!r} is unmapped"
    assert set(NAMES) == set(get_args(IconToken)) | set(get_args(GlyphName))
    assert len(NAMES) == 27  # 22 conditions + 5 chrome


def test_every_mapped_name_is_vendored_in_all_three_styles() -> None:
    # Offline guard: each meteocons name the map references is present as a
    # vendored SVG in flat, line, AND mono - so no pack can ask for a file the
    # kiosk would have to fetch.
    for style in _STYLES:
        for meteocons_name in set(NAMES.values()):
            svg = _SVG_ROOT / style / f"{meteocons_name}.svg"
            assert svg.is_file(), f"missing vendored SVG {svg}"


def test_generated_css_matches_committed_disk_file() -> None:
    # The committed pack.css (served at /pack.css) must be exactly what the
    # generator emits - regenerate on change, never hand-edit.
    for style in _STYLES:
        disk = (_STATIC / "packs" / f"meteocons-{style}" / "pack.css").read_text(
            encoding="utf-8"
        )
        assert pack_css(style) == disk, f"meteocons-{style}/pack.css drifted from generator"


def test_pack_css_rules_are_exactly_the_27_names() -> None:
    # No dead rules, no missing ones: each style's CSS styles precisely the union.
    expected = set(get_args(IconToken)) | set(get_args(GlyphName))
    for style in _STYLES:
        assert _rule_names(pack_css(style)) == expected
