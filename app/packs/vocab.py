"""The chrome-glyph vocabulary every icon pack implements.

Unlike the weather `IconToken` (resolved day/night by app.weather_codes.describe
and carried in the data contract), chrome glyphs are requested directly by a
layout and never touch /api/data. Every pack maps `IconToken | GlyphName`, so
its glyph table is total over both; a `Literal` makes a bad name a type error
rather than a missing glyph at runtime.
"""

from __future__ import annotations

from typing import Final, Literal, get_args

GlyphName = Literal["wind", "humidity", "precip", "sunrise", "sunset"]

# Derived from the Literal so it cannot drift from it.
GLYPH_NAMES: Final[frozenset[GlyphName]] = frozenset(get_args(GlyphName))
