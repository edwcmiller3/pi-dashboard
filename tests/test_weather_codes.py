"""Tests for the WMO weather-code -> icon/label mapping (Open-Meteo codes).

Written test-first (TDD). The mapping is the single source of truth for both
the vendored weather-icons font subset and the weather transform, so these
tests also guard that no glyph outside the subset can sneak in.
"""

from __future__ import annotations

import re
from itertools import product
from pathlib import Path

import pytest

from app import weather_codes as wc

# The vendored, subset weather-icons CSS — the real source of truth for which
# glyphs actually ship in the font. Parsed live so the test fails if the module
# can emit a glyph that wasn't subset into static/vendor/.
_VENDOR_CSS = (
    Path(__file__).resolve().parent.parent
    / "static"
    / "vendor"
    / "weather-icons"
    / "weather-icons.css"
)
VENDORED_CSS_CLASSES = frozenset(
    re.findall(r"\.(wi-[a-z0-9-]+)::before", _VENDOR_CSS.read_text())
)

# Hero stat-cell icons vendored for the current-weather card; they have no WMO
# code mapping, so the weather-code glyph set is the CSS classes minus these.
STAT_ICONS = frozenset(
    {"wi-strong-wind", "wi-humidity", "wi-raindrop", "wi-sunrise", "wi-sunset"}
)

# The glyphs the code->icon mapping is allowed to emit: every vendored class that
# isn't a hero stat icon. Derived from the CSS (not hand-listed) so adding a glyph
# is a one-place edit and no hand-maintained copy can drift out of sync.
ALLOWED_GLYPHS = VENDORED_CSS_CLASSES - STAT_ICONS

# Every WMO interpretation code Open-Meteo documents.
ALL_CODES = [
    0, 1, 2, 3, 45, 48, 51, 53, 55, 56, 57, 61, 63, 65, 66, 67, 71, 73, 75,
    77, 80, 81, 82, 85, 86, 95, 96, 99,
]  # fmt: skip

# Codes outside the documented set — must still resolve (to the wi-na fallback).
UNKNOWN_CODES = [123, -1, 9999]


def test_clear_day_and_night() -> None:
    assert wc.describe(0, is_day=True) == {"icon": "wi-day-sunny", "text": "Clear"}
    assert wc.describe(0, is_day=False)["icon"] == "wi-night-clear"


def test_mainly_clear_is_distinct_from_clear() -> None:
    # Detailed granularity keeps "mainly clear" (1) separate from "clear" (0).
    assert wc.describe(1, is_day=True)["icon"] == "wi-day-sunny-overcast"
    assert wc.describe(1, is_day=False)["icon"] == "wi-night-alt-cloudy-high"
    assert wc.describe(1)["text"] == "Mainly clear"


@pytest.mark.parametrize("code", [3, 45, 95])
def test_neutral_buckets_ignore_is_day(code: int) -> None:
    # Overcast/fog/mix/storm look the same day or night -> same glyph.
    assert (
        wc.describe(code, is_day=True)["icon"]
        == wc.describe(code, is_day=False)["icon"]
    )


def test_showers_distinct_from_steady_rain() -> None:
    assert wc.describe(63, is_day=True)["icon"] == "wi-day-rain"  # steady
    assert wc.describe(81, is_day=True)["icon"] == "wi-day-showers"  # showers
    assert wc.describe(85, is_day=True)["icon"] == "wi-day-sleet"  # snow showers


@pytest.mark.parametrize("code", [95, 96, 99])
def test_thunderstorm_family_is_generic_storm(code: int) -> None:
    assert wc.describe(code)["icon"] == "wi-thunderstorm"


def test_unknown_code_falls_back_to_na() -> None:
    out = wc.describe(123)
    assert out["icon"] == "wi-na"
    assert out["text"]  # non-empty label, doesn't crash


@pytest.mark.parametrize("code", ALL_CODES)
def test_every_documented_code_is_mapped(code: int) -> None:
    out = wc.describe(code)
    assert out["icon"] in ALLOWED_GLYPHS  # a real vendored glyph, no tofu
    assert out["text"]  # non-empty label


@pytest.mark.parametrize(
    ("code", "is_day"), list(product(ALL_CODES + UNKNOWN_CODES, [True, False]))
)
def test_no_code_maps_outside_the_vendored_subset(code: int, is_day: bool) -> None:
    # Every code (documented or not), day or night, resolves to a vendored glyph.
    assert wc.describe(code, is_day=is_day)["icon"] in ALLOWED_GLYPHS


def test_describe_defaults_to_day() -> None:
    assert wc.describe(0) == wc.describe(0, is_day=True)


# ── is_wet: does this code precipitate? (gates the forecast precip line) ──────

# Non-precip codes: clear (0), mainly clear (1), partly cloudy (2), overcast (3),
# fog (45), rime fog (48). Everything else Open-Meteo documents falls in a
# drizzle/rain/snow/showers/thunderstorm family and does precipitate.
DRY_CODES = [0, 1, 2, 3, 45, 48]
WET_CODES = [c for c in ALL_CODES if c not in DRY_CODES]


@pytest.mark.parametrize("code", DRY_CODES)
def test_is_wet_false_for_clear_cloud_and_fog(code: int) -> None:
    assert wc.is_wet(code) is False


@pytest.mark.parametrize("code", WET_CODES)
def test_is_wet_true_for_every_precip_family(code: int) -> None:
    # drizzle/rain/snow/showers/thunderstorm all precipitate (rain OR snow) — the
    # user's gate is "any precip", not "rain only" (2026-07-01).
    assert wc.is_wet(code) is True


@pytest.mark.parametrize("code", UNKNOWN_CODES)
def test_is_wet_false_for_unknown_codes(code: int) -> None:
    # An unmapped code can't be asserted to precipitate -> default dry (no line).
    assert wc.is_wet(code) is False


def test_is_wet_partitions_the_documented_codes() -> None:
    # Every documented code is either wet or dry, never both / neither — so the
    # predicate can't silently drop a code as the mapping grows.
    assert {c for c in ALL_CODES if wc.is_wet(c)} == set(WET_CODES)


def test_emittable_glyphs_exactly_match_the_vendored_weather_subset() -> None:
    # Two-way guard, self-maintaining (no hand-listed copy to drift):
    #   * every glyph the module can emit is vendored -> no tofu on the kiosk;
    #   * every vendored non-stat glyph is actually emittable -> no dead weight
    #     shipped in the font subset.
    assert wc.glyphs() == ALLOWED_GLYPHS
