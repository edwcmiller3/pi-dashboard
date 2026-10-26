"""Tests for the WMO weather-code -> condition-token/label mapping (Open-Meteo).

The token -> glyph tofu guard lives in tests/test_weather_icons_pack.py.
"""

from __future__ import annotations

from itertools import product
from typing import get_args

import pytest

from app import weather_codes as wc

TOKENS = frozenset(get_args(wc.IconToken))

# Every WMO interpretation code Open-Meteo documents.
ALL_CODES = [
    0, 1, 2, 3, 45, 48, 51, 53, 55, 56, 57, 61, 63, 65, 66, 67, 71, 73, 75,
    77, 80, 81, 82, 85, 86, 95, 96, 99,
]  # fmt: skip

UNKNOWN_CODES = [123, -1, 9999]


def test_clear_day_and_night() -> None:
    assert wc.describe(0, is_day=True) == {"icon": "clear-day", "text": "Clear"}
    assert wc.describe(0, is_day=False)["icon"] == "clear-night"


def test_mainly_clear_is_distinct_from_clear() -> None:
    assert wc.describe(1, is_day=True)["icon"] == "mostly-clear-day"
    assert wc.describe(1, is_day=False)["icon"] == "mostly-clear-night"
    assert wc.describe(1)["text"] == "Mainly clear"


@pytest.mark.parametrize("code", [3, 45, 95])
def test_neutral_conditions_ignore_is_day(code: int) -> None:
    assert (
        wc.describe(code, is_day=True)["icon"]
        == wc.describe(code, is_day=False)["icon"]
    )


def test_showers_distinct_from_steady_rain() -> None:
    assert wc.describe(63, is_day=True)["icon"] == "rain-day"  # steady
    assert wc.describe(81, is_day=True)["icon"] == "showers-day"  # showers
    assert wc.describe(85, is_day=True)["icon"] == "snow-showers-day"  # snow showers


@pytest.mark.parametrize("code", [95, 96, 99])
def test_thunderstorm_family_is_generic_storm(code: int) -> None:
    assert wc.describe(code)["icon"] == "thunderstorm"


def test_unknown_code_falls_back_to_not_available() -> None:
    out = wc.describe(123)
    assert out["icon"] == "not-available"
    assert out["text"]  # non-empty label, doesn't crash


@pytest.mark.parametrize("code", ALL_CODES)
def test_every_documented_code_is_mapped(code: int) -> None:
    out = wc.describe(code)
    assert out["icon"] in TOKENS  # a declared IconToken, never an ad-hoc string
    assert out["text"]  # non-empty label


@pytest.mark.parametrize(
    ("code", "is_day"), list(product(ALL_CODES + UNKNOWN_CODES, [True, False]))
)
def test_no_code_maps_outside_the_token_vocabulary(code: int, is_day: bool) -> None:
    assert wc.describe(code, is_day=is_day)["icon"] in TOKENS


def test_describe_defaults_to_day() -> None:
    assert wc.describe(0) == wc.describe(0, is_day=True)


# ── Per-code identity: the authoritative token table ─────────────────────────
#
# Membership alone lets a transposition to another valid token (snow ->
# showers) stay green. Hand-written, not derived from `_WMO`, so it constrains
# the mapping rather than mirroring it.
EXPECTED: dict[int, tuple[str, str]] = {
    0: ("clear-day", "clear-night"),
    1: ("mostly-clear-day", "mostly-clear-night"),
    2: ("partly-cloudy-day", "partly-cloudy-night"),
    3: ("overcast", "overcast"),
    45: ("fog", "fog"),
    48: ("fog", "fog"),
    51: ("drizzle-day", "drizzle-night"),
    53: ("drizzle-day", "drizzle-night"),
    55: ("drizzle-day", "drizzle-night"),
    56: ("freezing-drizzle", "freezing-drizzle"),
    57: ("freezing-drizzle", "freezing-drizzle"),
    61: ("rain-day", "rain-night"),
    63: ("rain-day", "rain-night"),
    65: ("rain-day", "rain-night"),
    66: ("freezing-rain", "freezing-rain"),
    67: ("freezing-rain", "freezing-rain"),
    71: ("snow-day", "snow-night"),
    73: ("snow-day", "snow-night"),
    75: ("snow-day", "snow-night"),
    77: ("snow-day", "snow-night"),
    80: ("showers-day", "showers-night"),
    81: ("showers-day", "showers-night"),
    82: ("showers-day", "showers-night"),
    85: ("snow-showers-day", "snow-showers-night"),
    86: ("snow-showers-day", "snow-showers-night"),
    95: ("thunderstorm", "thunderstorm"),
    96: ("thunderstorm", "thunderstorm"),
    99: ("thunderstorm", "thunderstorm"),
}


def test_expected_identity_table_covers_exactly_the_documented_codes() -> None:
    # So a code added to the mapping can't escape the per-code identity pin.
    assert set(EXPECTED) == set(wc.WMO) == set(ALL_CODES)


@pytest.mark.parametrize(("code", "expected"), list(EXPECTED.items()))
def test_each_documented_code_resolves_to_its_exact_tokens(
    code: int, expected: tuple[str, str]
) -> None:
    day_expected, night_expected = expected
    assert wc.describe(code, is_day=True)["icon"] == day_expected
    assert wc.describe(code, is_day=False)["icon"] == night_expected


@pytest.mark.parametrize("code", UNKNOWN_CODES)
def test_unknown_codes_resolve_to_not_available_day_and_night(code: int) -> None:
    assert wc.describe(code, is_day=True)["icon"] == "not-available"
    assert wc.describe(code, is_day=False)["icon"] == "not-available"


# ── is_wet: does this code precipitate? (gates the forecast precip line) ──────

# Clear, mainly clear, partly cloudy, overcast, fog, rime fog.
DRY_CODES = [0, 1, 2, 3, 45, 48]
WET_CODES = [c for c in ALL_CODES if c not in DRY_CODES]


@pytest.mark.parametrize("code", DRY_CODES)
def test_is_wet_false_for_clear_cloud_and_fog(code: int) -> None:
    assert wc.is_wet(code) is False


@pytest.mark.parametrize("code", WET_CODES)
def test_is_wet_true_for_every_precip_family(code: int) -> None:
    # The gate is any precip (rain or snow), not rain only.
    assert wc.is_wet(code) is True


@pytest.mark.parametrize("code", UNKNOWN_CODES)
def test_is_wet_false_for_unknown_codes(code: int) -> None:
    assert wc.is_wet(code) is False


def test_is_wet_partitions_the_documented_codes() -> None:
    # So the predicate can't silently drop a code as the mapping grows.
    assert {c for c in ALL_CODES if wc.is_wet(c)} == set(WET_CODES)
