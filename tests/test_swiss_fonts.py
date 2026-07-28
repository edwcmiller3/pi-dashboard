"""Tests for the vendored, subset swiss-mono fonts (static/vendor/fonts/).

Same two-way-pin spirit as tests/test_hud_fonts.py, but for the swiss-mono
layout's faces and its OWN manifest (subset-manifest-swiss-mono.txt) - the two
layouts need different unicode sets, so they keep separate manifests + pins.

The pin is self-maintaining off the vendored artifacts themselves (the manifest's
--unicodes line + the actual woff2 cmaps), so there is no hand-listed glyph copy
that can silently drift:

  * every codepoint the manifest requests is in every vendored subset
    -> no tofu on the kiosk;
  * every codepoint in a subset is one the manifest actually requested
    -> no dead weight shipped in the font;
  * the three marks the design renders as REAL glyphs (↑ ↓ ●) ARE present in
    every subset -> unlike the HUD's ◆▸◂▲▼⟳ (drawn as SVG because absent), these
    subset directly, so nobody may quietly reintroduce an SVG fallback for them.
"""

from __future__ import annotations

import re
from pathlib import Path

from fontTools.ttLib import TTFont

_FONTS_DIR = Path(__file__).resolve().parent.parent / "static" / "vendor" / "fonts"
_MANIFEST = _FONTS_DIR / "subset-manifest-swiss-mono.txt"

# The six faces the swiss-mono layout wires up (Inter 400/600/700/800;
# JetBrains Mono 500/700).
SUBSET_FILES = (
    "inter-400.woff2",
    "inter-600.woff2",
    "inter-700.woff2",
    "inter-800.woff2",
    "jetbrains-mono-500.woff2",
    "jetbrains-mono-700.woff2",
)

# The marks the design renders as real font glyphs (mono runs) - pinned PRESENT.
SELF_HOSTED_MARKS = {0x00B0, 0x00B7, 0x2191, 0x2193, 0x25CF}  # ° · ↑ ↓ ●


def _codepoints(token: str) -> set[int]:
    """Expand one --unicodes token: 'U+0020-007E' (range) or 'U+00B0' (point)."""
    token = token.strip().removeprefix("U+")
    if "-" in token:
        lo, hi = token.split("-")
        return set(range(int(lo, 16), int(hi, 16) + 1))
    return {int(token, 16)}


def _requested() -> set[int]:
    """The authoritative pyftsubset --unicodes= set, straight from the manifest."""
    text = _MANIFEST.read_text()
    (unicodes_line,) = re.findall(r"--unicodes=(\S+)", text)
    requested: set[int] = set()
    for token in unicodes_line.split(","):
        requested |= _codepoints(token)
    return requested


# swiss-mono has NO fallback marks (every emitted glyph is vendored), so the
# expected cmap IS the requested set - no subtraction, unlike the HUD.
EXPECTED_CPS = _requested()


def _cmap(filename: str) -> set[int]:
    return set(TTFont(_FONTS_DIR / filename).getBestCmap().keys())


def test_all_subset_files_are_vendored_as_woff2() -> None:
    for name in SUBSET_FILES:
        path = _FONTS_DIR / name
        assert path.is_file(), f"missing vendored subset: {name}"
        assert TTFont(path).flavor == "woff2", f"{name} is not woff2"


def test_manifest_declares_the_expected_set() -> None:
    # Guard the parser: if the manifest format changes and the set comes back
    # empty/degenerate, the pins below would pass vacuously.
    assert 0x30 in EXPECTED_CPS and 0x39 in EXPECTED_CPS  # mono digits 0-9
    assert 0x25 in EXPECTED_CPS  # %
    assert SELF_HOSTED_MARKS <= EXPECTED_CPS  # ° · ↑ ↓ ● all requested
    assert len(EXPECTED_CPS) >= 95  # basic Latin + the marks


def test_each_subset_cmap_matches_the_manifest_exactly() -> None:
    # The core two-way pin, per face: the woff2 carries exactly the requested
    # glyphs -> no tofu (missing) and no dead weight (extra). Any drift in the
    # manifest or a re-subset breaks this.
    for name in SUBSET_FILES:
        assert _cmap(name) == EXPECTED_CPS, f"{name} cmap != manifest requested set"


def test_self_hosted_marks_are_present_in_every_subset() -> None:
    # The inverse of the HUD's absent-marks pin: ↑ ↓ ● (and ° ·) MUST ship in
    # every face, since the swiss-mono layout emits them as text with no SVG
    # fallback. If a future re-subset or source-font swap dropped one, this fails
    # and forces a deliberate decision (re-add the glyph, or draw it as SVG).
    for name in SUBSET_FILES:
        assert SELF_HOSTED_MARKS <= _cmap(name), f"{name} is missing a self-hosted mark"
