"""WMO weather-code -> weather-icons glyph + label (Open-Meteo interpretation).

Pure, functional, no classes: an immutable lookup table plus pure functions.
Single source of truth for (a) the vendored weather-icons font subset and
(b) the Phase-4 weather transform that resolves `icon`/`text` for the data
contract. The frontend never sees raw WMO codes.

Granularity: "Detailed" (2026-06-28 decision). Day/night variants come from
Open-Meteo's free `is_day` field; neutral buckets (overcast/fog/mix/storm)
use one glyph for both. NOTE: these are Open-Meteo WMO *interpretation* codes,
deliberately mapped by hand from Open-Meteo's documented list -- NOT the
weather-icons `wi-wmo4680-*` set, which encodes different WMO 4680 codes.
"""

from __future__ import annotations

from types import MappingProxyType
from typing import TypedDict


class Condition(TypedDict):
    icon: str  # a weather-icons class, e.g. "wi-day-rain"
    text: str  # short human label, e.g. "Light rain"


# code -> (day glyph, night glyph, label). Neutral buckets repeat the glyph.
_WMO: dict[int, tuple[str, str, str]] = {
    0: ("wi-day-sunny", "wi-night-clear", "Clear"),
    1: ("wi-day-sunny-overcast", "wi-night-alt-cloudy-high", "Mainly clear"),
    2: ("wi-day-cloudy", "wi-night-alt-cloudy", "Partly cloudy"),
    3: ("wi-cloudy", "wi-cloudy", "Overcast"),
    45: ("wi-fog", "wi-fog", "Fog"),
    48: ("wi-fog", "wi-fog", "Rime fog"),
    51: ("wi-day-sprinkle", "wi-night-alt-sprinkle", "Light drizzle"),
    53: ("wi-day-sprinkle", "wi-night-alt-sprinkle", "Drizzle"),
    55: ("wi-day-sprinkle", "wi-night-alt-sprinkle", "Heavy drizzle"),
    56: ("wi-rain-mix", "wi-rain-mix", "Freezing drizzle"),
    57: ("wi-rain-mix", "wi-rain-mix", "Freezing drizzle"),
    61: ("wi-day-rain", "wi-night-alt-rain", "Light rain"),
    63: ("wi-day-rain", "wi-night-alt-rain", "Rain"),
    65: ("wi-day-rain", "wi-night-alt-rain", "Heavy rain"),
    66: ("wi-rain-mix", "wi-rain-mix", "Freezing rain"),
    67: ("wi-rain-mix", "wi-rain-mix", "Freezing rain"),
    71: ("wi-day-snow", "wi-night-alt-snow", "Light snow"),
    73: ("wi-day-snow", "wi-night-alt-snow", "Snow"),
    75: ("wi-day-snow", "wi-night-alt-snow", "Heavy snow"),
    77: ("wi-day-snow", "wi-night-alt-snow", "Snow grains"),
    80: ("wi-day-showers", "wi-night-alt-showers", "Light showers"),
    81: ("wi-day-showers", "wi-night-alt-showers", "Showers"),
    82: ("wi-day-showers", "wi-night-alt-showers", "Violent showers"),
    85: ("wi-day-sleet", "wi-sleet", "Snow showers"),
    86: ("wi-day-sleet", "wi-sleet", "Snow showers"),
    95: ("wi-thunderstorm", "wi-thunderstorm", "Thunderstorm"),
    96: ("wi-thunderstorm", "wi-thunderstorm", "Thunderstorm with hail"),
    99: ("wi-thunderstorm", "wi-thunderstorm", "Thunderstorm with hail"),
}

# Read-only view -> the table can't be mutated at runtime.
WMO = MappingProxyType(_WMO)

_UNKNOWN: tuple[str, str, str] = ("wi-na", "wi-na", "Unknown")


def describe(code: int, is_day: bool = True) -> Condition:
    """Resolve a WMO code (+ day/night) to its icon class and label.

    Unknown codes fall back to the `wi-na` glyph rather than raising, so a
    surprise code from the API can never break rendering.
    """
    day, night, label = _WMO.get(code, _UNKNOWN)
    return {"icon": day if is_day else night, "text": label}


def glyphs() -> frozenset[str]:
    """Every weather-icons class this module can emit (incl. the fallback).

    Drives the font subset: exactly these glyphs are vendored.
    """
    used = {g for day, night, _ in _WMO.values() for g in (day, night)}
    used.add(_UNKNOWN[0])
    return frozenset(used)
