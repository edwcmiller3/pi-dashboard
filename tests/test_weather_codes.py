"""Tests for the WMO weather-code -> icon/label mapping (Open-Meteo codes).

Written test-first (TDD). The mapping is the single source of truth for both
the vendored weather-icons font subset and the Phase-4 weather transform, so
these tests also guard that no glyph outside the subset can sneak in.
"""

import re
from pathlib import Path

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
VENDORED_CSS_CLASSES = set(
    re.findall(r"\.(wi-[a-z0-9-]+)::before", _VENDOR_CSS.read_text())
)

# The exact glyph set we vendor (Detailed granularity, 2026-06-28). If a code
# maps to anything outside this, the font subset would be missing a glyph.
VENDORED = {
    "wi-day-sunny",
    "wi-night-clear",
    "wi-day-sunny-overcast",
    "wi-night-alt-cloudy-high",
    "wi-day-cloudy",
    "wi-night-alt-cloudy",
    "wi-cloudy",
    "wi-fog",
    "wi-day-sprinkle",
    "wi-night-alt-sprinkle",
    "wi-rain-mix",
    "wi-day-rain",
    "wi-night-alt-rain",
    "wi-day-showers",
    "wi-night-alt-showers",
    "wi-day-snow",
    "wi-night-alt-snow",
    "wi-day-sleet",
    "wi-sleet",
    "wi-thunderstorm",
    "wi-na",  # fallback for unknown codes
}

# Every WMO interpretation code Open-Meteo documents.
ALL_CODES = [
    0,
    1,
    2,
    3,
    45,
    48,
    51,
    53,
    55,
    56,
    57,
    61,
    63,
    65,
    66,
    67,
    71,
    73,
    75,
    77,
    80,
    81,
    82,
    85,
    86,
    95,
    96,
    99,
]


def test_clear_day_and_night() -> None:
    assert wc.describe(0, is_day=True) == {"icon": "wi-day-sunny", "text": "Clear"}
    assert wc.describe(0, is_day=False)["icon"] == "wi-night-clear"


def test_mainly_clear_is_distinct_from_clear() -> None:
    # Detailed granularity keeps "mainly clear" (1) separate from "clear" (0).
    assert wc.describe(1, is_day=True)["icon"] == "wi-day-sunny-overcast"
    assert wc.describe(1, is_day=False)["icon"] == "wi-night-alt-cloudy-high"
    assert wc.describe(1)["text"] == "Mainly clear"


def test_neutral_buckets_ignore_is_day() -> None:
    # Overcast/fog/mix/storm look the same day or night -> same glyph.
    for code in (3, 45, 95):
        assert (
            wc.describe(code, is_day=True)["icon"]
            == wc.describe(code, is_day=False)["icon"]
        )


def test_showers_distinct_from_steady_rain() -> None:
    assert wc.describe(63, is_day=True)["icon"] == "wi-day-rain"  # steady
    assert wc.describe(81, is_day=True)["icon"] == "wi-day-showers"  # showers
    assert wc.describe(85, is_day=True)["icon"] == "wi-day-sleet"  # snow showers


def test_thunderstorm_family_is_generic_storm() -> None:
    for code in (95, 96, 99):
        assert wc.describe(code)["icon"] == "wi-thunderstorm"


def test_unknown_code_falls_back_to_na() -> None:
    out = wc.describe(123)
    assert out["icon"] == "wi-na"
    assert out["text"]  # non-empty label, doesn't crash


def test_every_documented_code_is_mapped() -> None:
    for code in ALL_CODES:
        out = wc.describe(code)
        assert out["icon"] in VENDORED
        assert out["text"]


def test_no_code_maps_outside_the_vendored_subset() -> None:
    for code in ALL_CODES + [123, -1, 9999]:
        for is_day in (True, False):
            assert wc.describe(code, is_day=is_day)["icon"] in VENDORED


def test_describe_defaults_to_day() -> None:
    assert wc.describe(0) == wc.describe(0, is_day=True)


def test_vendored_font_covers_every_emittable_glyph() -> None:
    # Every glyph the module can emit must have a class in the vendored subset
    # CSS, or it would render as tofu on the kiosk.
    missing = wc.glyphs() - VENDORED_CSS_CLASSES
    assert not missing, f"glyphs not vendored in weather-icons.css: {sorted(missing)}"


def test_hand_maintained_subset_matches_vendored_css() -> None:
    # The hand-listed VENDORED set must stay in sync with what's actually
    # shipped (minus the 5 hero stat icons, which have no WMO mapping).
    stat_icons = {
        "wi-strong-wind",
        "wi-humidity",
        "wi-raindrop",
        "wi-sunrise",
        "wi-sunset",
    }
    assert VENDORED == VENDORED_CSS_CLASSES - stat_icons
