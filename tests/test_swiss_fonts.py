"""Tests for the vendored, subset swiss-mono fonts (static/vendor/fonts/).

The same two-way pin as tests/test_hud_fonts.py, against swiss-mono's own
manifest (subset-manifest-swiss-mono.txt) - the layouts need different unicode
sets. Unlike the HUD's SVG-drawn marks, swiss-mono renders ↑ ↓ ● as real glyphs,
so they're pinned present.
"""

from __future__ import annotations

import re
from pathlib import Path

from fontTools.ttLib import TTFont

_FONTS_DIR = Path(__file__).resolve().parent.parent / "static" / "vendor" / "fonts"
_MANIFEST = _FONTS_DIR / "subset-manifest-swiss-mono.txt"

SUBSET_FILES = (
    "inter-400.woff2",
    "inter-600.woff2",
    "inter-700.woff2",
    "inter-800.woff2",
    "jetbrains-mono-500.woff2",
    "jetbrains-mono-700.woff2",
)

SELF_HOSTED_MARKS = {0x00B0, 0x00B7, 0x2191, 0x2193, 0x25CF}  # ° · ↑ ↓ ●


def _codepoints(token: str) -> set[int]:
    """Expand one --unicodes token: 'U+0020-007E' (range) or 'U+00B0' (point)."""
    token = token.strip().removeprefix("U+")
    if "-" in token:
        lo, hi = token.split("-")
        return set(range(int(lo, 16), int(hi, 16) + 1))
    return {int(token, 16)}


def _requested() -> set[int]:
    """The manifest's pyftsubset --unicodes= set."""
    text = _MANIFEST.read_text()
    (unicodes_line,) = re.findall(r"--unicodes=(\S+)", text)
    requested: set[int] = set()
    for token in unicodes_line.split(","):
        requested |= _codepoints(token)
    return requested


# No fallback marks to subtract, unlike the HUD.
EXPECTED_CPS = _requested()


def _cmap(filename: str) -> set[int]:
    return set(TTFont(_FONTS_DIR / filename).getBestCmap().keys())


def test_all_subset_files_are_vendored_as_woff2() -> None:
    for name in SUBSET_FILES:
        path = _FONTS_DIR / name
        assert path.is_file(), f"missing vendored subset: {name}"
        assert TTFont(path).flavor == "woff2", f"{name} is not woff2"


def test_manifest_declares_the_expected_set() -> None:
    # Guards the parser: an empty set would make the pins below pass vacuously.
    assert 0x30 in EXPECTED_CPS and 0x39 in EXPECTED_CPS  # mono digits 0-9
    assert 0x25 in EXPECTED_CPS  # %
    assert SELF_HOSTED_MARKS <= EXPECTED_CPS  # ° · ↑ ↓ ● all requested
    assert len(EXPECTED_CPS) >= 95  # basic Latin + the marks


def test_each_subset_cmap_matches_the_manifest_exactly() -> None:
    for name in SUBSET_FILES:
        assert _cmap(name) == EXPECTED_CPS, f"{name} cmap != manifest requested set"


def test_self_hosted_marks_are_present_in_every_subset() -> None:
    # Emitted as text with no SVG fallback; dropping one must be a deliberate
    # decision (re-add the glyph, or draw it as SVG).
    for name in SUBSET_FILES:
        assert SELF_HOSTED_MARKS <= _cmap(name), f"{name} is missing a self-hosted mark"
