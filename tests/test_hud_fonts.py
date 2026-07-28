"""Tests for the vendored, subset HUD fonts (static/vendor/fonts/).

Front-loaded Phase 3 prep. Mirrors the two-way-pin spirit of
tests/test_weather_codes.py:143-148: the pin is self-maintaining off the
vendored artifacts themselves (the subset manifest + the actual woff2 cmaps),
so there is no hand-listed glyph copy that can silently drift.

  * every glyph the HUD emits and self-hosts is in every vendored subset
    -> no tofu on the kiosk;
  * every codepoint in a subset is one the manifest actually requested
    -> no dead weight shipped in the font;
  * the six geometric marks the HUD also emits (◆ ▸ ◂ ▲ ▼ ⟳) are NOT in these
    two mono fonts, so they are pinned ABSENT -> nobody may quietly assume they
    ship here (they render via OS fallback in the mock; Phase 3 must resolve
    them as SVG/CSS or a dedicated glyph font). See subset-manifest.txt.
"""

from __future__ import annotations

import re
from pathlib import Path

from fontTools.ttLib import TTFont

_FONTS_DIR = Path(__file__).resolve().parent.parent / "static" / "vendor" / "fonts"
_MANIFEST = _FONTS_DIR / "subset-manifest.txt"

# The four faces the HUD wires up (Share Tech Mono 400; IBM Plex Mono 400/500/600).
SUBSET_FILES = (
    "share-tech-mono.woff2",
    "ibm-plex-mono-400.woff2",
    "ibm-plex-mono-500.woff2",
    "ibm-plex-mono-600.woff2",
)


def _codepoints(token: str) -> set[int]:
    """Expand one --unicodes token: 'U+0020-007E' (range) or 'U+00B0' (point)."""
    token = token.strip().removeprefix("U+")
    if "-" in token:
        lo, hi = token.split("-")
        return set(range(int(lo, 16), int(hi, 16) + 1))
    return {int(token, 16)}


def _parse_manifest() -> tuple[set[int], set[int]]:
    """Derive (requested, fallback) codepoint sets straight from the manifest.

    requested = the authoritative pyftsubset --unicodes= line.
    fallback  = the U+XXXX marks listed in the FALLBACK_SYMBOLS block (absent
                from both source fonts, so pinned out of every subset).
    """
    text = _MANIFEST.read_text()

    (unicodes_line,) = re.findall(r"--unicodes=(\S+)", text)
    requested: set[int] = set()
    for token in unicodes_line.split(","):
        requested |= _codepoints(token)

    fallback_block = text.split("FALLBACK_SYMBOLS", 1)[1]
    fallback = {int(h, 16) for h in re.findall(r"U\+([0-9A-Fa-f]{4,6})", fallback_block)}

    return requested, fallback


REQUESTED_CPS, FALLBACK_CPS = _parse_manifest()
# What every subset must contain, exactly: everything requested that the source
# fonts could actually provide.
EXPECTED_CPS = REQUESTED_CPS - FALLBACK_CPS


def _cmap(filename: str) -> set[int]:
    return set(TTFont(_FONTS_DIR / filename).getBestCmap().keys())


def test_all_subset_files_are_vendored_as_woff2() -> None:
    for name in SUBSET_FILES:
        path = _FONTS_DIR / name
        assert path.is_file(), f"missing vendored subset: {name}"
        assert TTFont(path).flavor == "woff2", f"{name} is not woff2"


def test_manifest_declares_something_and_a_known_gap() -> None:
    # Guard the parser itself: if the manifest format changes and the sets come
    # back empty, the pins below would pass vacuously.
    assert 0x30 in EXPECTED_CPS and 0x39 in EXPECTED_CPS  # mono digits 0-9
    assert 0x25 in EXPECTED_CPS  # %
    assert 0x00B0 in EXPECTED_CPS and 0x00B7 in EXPECTED_CPS  # ° ·
    assert len(EXPECTED_CPS) >= 95  # basic Latin + the marks
    assert FALLBACK_CPS == {0x25C6, 0x25B8, 0x25C2, 0x25B2, 0x25BC, 0x27F3}


def test_each_subset_cmap_matches_the_manifest_exactly() -> None:
    # The core two-way pin, per face: the woff2 carries exactly the requested
    # glyphs the fonts could provide -> no tofu (missing) and no dead weight
    # (extra). Any drift in the manifest or the subset breaks this.
    for name in SUBSET_FILES:
        assert _cmap(name) == EXPECTED_CPS, f"{name} cmap != manifest EXPECTED set"


def test_fallback_marks_are_absent_from_every_subset() -> None:
    # The six geometric marks are pinned ABSENT. If a future re-subset (or a
    # different source font) ever includes one, this fails and forces the
    # manifest's FALLBACK_SYMBOLS note to be updated deliberately.
    for name in SUBSET_FILES:
        assert not (_cmap(name) & FALLBACK_CPS), f"{name} unexpectedly ships a fallback mark"
