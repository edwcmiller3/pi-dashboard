"""The shared chrome-glyph vocabulary every icon pack implements.

`GlyphName` is the fixed set of UI/stat chrome glyphs a layout requests directly
(wind / humidity / precip / sunrise / sunset). Unlike the weather `IconToken`
(which app.weather_codes.describe resolves day/night from a WMO code and which
flows through the data contract), chrome names are flat and never touch
/api/data - they are the frontend's own glyph vocabulary. Every pack maps
`IconToken` and `GlyphName` together, so a pack's glyph table is TOTAL over the
union of the two (22 + 5 = 27 names).

Making `GlyphName` a `Literal` (not a bare `str`) means a pack's chrome entries
carry a real, checkable vocabulary end to end: a bad chrome name fails the
type-check rather than surfacing as a missing glyph at runtime.
"""

from __future__ import annotations

from typing import Final, Literal, get_args

# The closed set of chrome-glyph names. `IconToken` (the weather conditions)
# continues to live in app/weather_codes.py; a pack imports from both homes.
GlyphName = Literal["wind", "humidity", "precip", "sunrise", "sunset"]

# Immutable, typed view of the vocabulary for iteration (tests / a pack's
# completeness check). Derived from the Literal so it cannot drift from it.
GLYPH_NAMES: Final[frozenset[GlyphName]] = frozenset(get_args(GlyphName))
