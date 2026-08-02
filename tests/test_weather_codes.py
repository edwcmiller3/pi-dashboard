"""Tests for the WMO weather-code -> condition-token/label mapping (Open-Meteo).

Written test-first (TDD). The mapping is the single source of truth for the
weather transform: it resolves every WMO code (+ day/night) to a semantic
`IconToken` and a human label. These tests guard that no token outside the
declared vocabulary can sneak in, and that the day/night resolution is correct.

The font-subset / tofu guard (every emitted token maps to a real, in-font
glyph, with no dead weight shipped) now lives in the weather-icons pack test -
`tests/test_weather_icons_pack.py::test_every_pack_codepoint_is_in_the_vendored_woff2_subset`
- which owns the token -> glyph mapping and its generated CSS.
"""

from __future__ import annotations

from itertools import product
from typing import get_args

import pytest

from app import weather_codes as wc

# The declared IconToken vocabulary - the closed set describe() may emit. Read
# off the Literal itself (not hand-listed) so the guard tracks the source.
TOKENS = frozenset(get_args(wc.IconToken))

# Every WMO interpretation code Open-Meteo documents.
ALL_CODES = [
    0, 1, 2, 3, 45, 48, 51, 53, 55, 56, 57, 61, 63, 65, 66, 67, 71, 73, 75,
    77, 80, 81, 82, 85, 86, 95, 96, 99,
]  # fmt: skip

# Codes outside the documented set - must still resolve (to the not-available
# fallback).
UNKNOWN_CODES = [123, -1, 9999]


def test_clear_day_and_night() -> None:
    assert wc.describe(0, is_day=True) == {"icon": "clear-day", "text": "Clear"}
    assert wc.describe(0, is_day=False)["icon"] == "clear-night"


def test_mainly_clear_is_distinct_from_clear() -> None:
    # Detailed granularity keeps "mainly clear" (1) separate from "clear" (0).
    assert wc.describe(1, is_day=True)["icon"] == "mostly-clear-day"
    assert wc.describe(1, is_day=False)["icon"] == "mostly-clear-night"
    assert wc.describe(1)["text"] == "Mainly clear"


@pytest.mark.parametrize("code", [3, 45, 95])
def test_neutral_conditions_ignore_is_day(code: int) -> None:
    # Overcast/fog/storm look the same day or night -> same token.
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
    # Every code (documented or not), day or night, resolves to a declared token.
    assert wc.describe(code, is_day=is_day)["icon"] in TOKENS


def test_describe_defaults_to_day() -> None:
    assert wc.describe(0) == wc.describe(0, is_day=True)


# ── Per-code identity: the authoritative token table ─────────────────────────
#
# The membership tests above only prove describe() returns *some* declared
# IconToken. That is too weak: a transposition (WMO 71 snow returning
# "showers-day", or 56 freezing returning "drizzle-night") stays green because
# both are valid tokens. This table pins the EXACT (day, night) token every
# documented code must resolve to, so a future transposition goes red.
#
# Ground truth: enumerated from app/weather_codes.py `_WMO` and cross-checked,
# code by code, against the original wi-* mapping at
# `git show f13e0e1:app/weather_codes.py` (the refactor is behavior-preserving,
# so each token encodes the same condition the old wi-* class did):
#   wi-day-sunny/wi-night-clear -> clear-{day,night}
#   wi-day-sunny-overcast/wi-night-alt-cloudy-high -> mostly-clear-{day,night}
#   wi-day-cloudy/wi-night-alt-cloudy -> partly-cloudy-{day,night}
#   wi-cloudy -> overcast; wi-fog -> fog
#   wi-day-sprinkle/wi-night-alt-sprinkle -> drizzle-{day,night}
#   wi-rain-mix (56/57) -> freezing-drizzle; wi-rain-mix (66/67) -> freezing-rain
#   wi-day-rain/wi-night-alt-rain -> rain-{day,night}
#   wi-day-snow/wi-night-alt-snow -> snow-{day,night}
#   wi-day-showers/wi-night-alt-showers -> showers-{day,night}
#   wi-day-sleet (day) / wi-sleet (night) -> snow-showers-{day,night}
#   wi-thunderstorm -> thunderstorm; wi-na -> not-available
# This is a hand-written, independent expectation (not derived from `_WMO`), so
# it actually constrains the mapping rather than mirroring it.
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
    # The identity table and the module's `_WMO` cover the same code set, so a
    # code added to (or dropped from) the mapping can't silently escape the
    # per-code identity assertion below.
    assert set(EXPECTED) == set(wc.WMO) == set(ALL_CODES)


@pytest.mark.parametrize(("code", "expected"), list(EXPECTED.items()))
def test_each_documented_code_resolves_to_its_exact_tokens(
    code: int, expected: tuple[str, str]
) -> None:
    # Authoritative per-code identity: day AND night must equal the pinned
    # tokens exactly. A transposition to a *different but still valid* token
    # (e.g. snow -> showers) fails here even though the membership tests stay
    # green.
    day_expected, night_expected = expected
    assert wc.describe(code, is_day=True)["icon"] == day_expected
    assert wc.describe(code, is_day=False)["icon"] == night_expected


@pytest.mark.parametrize("code", UNKNOWN_CODES)
def test_unknown_codes_resolve_to_not_available_day_and_night(code: int) -> None:
    # The fallback identity, both branches: an unmapped code is "not-available"
    # for day and night alike, never some other valid token.
    assert wc.describe(code, is_day=True)["icon"] == "not-available"
    assert wc.describe(code, is_day=False)["icon"] == "not-available"


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
    # drizzle/rain/snow/showers/thunderstorm all precipitate (rain OR snow) - the
    # user's gate is "any precip", not "rain only" (2026-07-01).
    assert wc.is_wet(code) is True


@pytest.mark.parametrize("code", UNKNOWN_CODES)
def test_is_wet_false_for_unknown_codes(code: int) -> None:
    # An unmapped code can't be asserted to precipitate -> default dry (no line).
    assert wc.is_wet(code) is False


def test_is_wet_partitions_the_documented_codes() -> None:
    # Every documented code is either wet or dry, never both / neither - so the
    # predicate can't silently drop a code as the mapping grows.
    assert {c for c in ALL_CODES if wc.is_wet(c)} == set(WET_CODES)
