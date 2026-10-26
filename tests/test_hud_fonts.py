"""Tests for the vendored, subset HUD fonts (static/vendor/fonts/).

A two-way pin derived from the subset manifest and the actual woff2 cmaps (no
hand-listed glyph copy to drift): each subset ships exactly the requested
codepoints - no tofu, no dead weight. The six geometric marks (◆ ▸ ◂ ▲ ▼ ⟳)
are absent from both source fonts and pinned absent, since the HUD draws them
as SVG. See subset-manifest.txt.
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
    """(requested, fallback) codepoints: the pyftsubset --unicodes= line, and
    the marks in the FALLBACK_SYMBOLS block."""
    text = _MANIFEST.read_text()

    (unicodes_line,) = re.findall(r"--unicodes=(\S+)", text)
    requested: set[int] = set()
    for token in unicodes_line.split(","):
        requested |= _codepoints(token)

    fallback_block = text.split("FALLBACK_SYMBOLS", 1)[1]
    fallback = {int(h, 16) for h in re.findall(r"U\+([0-9A-Fa-f]{4,6})", fallback_block)}

    return requested, fallback


REQUESTED_CPS, FALLBACK_CPS = _parse_manifest()
EXPECTED_CPS = REQUESTED_CPS - FALLBACK_CPS


def _cmap(filename: str) -> set[int]:
    return set(TTFont(_FONTS_DIR / filename).getBestCmap().keys())


def test_all_subset_files_are_vendored_as_woff2() -> None:
    for name in SUBSET_FILES:
        path = _FONTS_DIR / name
        assert path.is_file(), f"missing vendored subset: {name}"
        assert TTFont(path).flavor == "woff2", f"{name} is not woff2"


def test_manifest_declares_something_and_a_known_gap() -> None:
    # Guards the parser: empty sets would make the pins below pass vacuously.
    assert 0x30 in EXPECTED_CPS and 0x39 in EXPECTED_CPS  # mono digits 0-9
    assert 0x25 in EXPECTED_CPS  # %
    assert 0x00B0 in EXPECTED_CPS and 0x00B7 in EXPECTED_CPS  # ° ·
    assert len(EXPECTED_CPS) >= 95  # basic Latin + the marks
    assert FALLBACK_CPS == {0x25C6, 0x25B8, 0x25C2, 0x25B2, 0x25BC, 0x27F3}


def test_each_subset_cmap_matches_the_manifest_exactly() -> None:
    for name in SUBSET_FILES:
        assert _cmap(name) == EXPECTED_CPS, f"{name} cmap != manifest EXPECTED set"


def test_fallback_marks_are_absent_from_every_subset() -> None:
    # A re-subset or font swap that ships one must update FALLBACK_SYMBOLS
    # deliberately.
    for name in SUBSET_FILES:
        assert not (_cmap(name) & FALLBACK_CPS), f"{name} unexpectedly ships a fallback mark"
