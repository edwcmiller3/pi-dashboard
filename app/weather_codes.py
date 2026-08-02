"""WMO weather-code -> condition token + label (Open-Meteo interpretation).

Pure, functional, no classes: an immutable lookup table plus pure functions.
Single source of truth for the weather transform that resolves `icon`/`text`
for the data contract. The frontend never sees raw WMO codes; it receives a
semantic, day/night-resolved `IconToken`, which an icon pack later maps to a
concrete glyph. The token preserves the full condition distinction even where a
pack collapses several tokens onto one drawing.

Granularity: "Detailed" - one entry per WMO interpretation code, not coarse
buckets. Day/night variants come from Open-Meteo's free `is_day` field; neutral
conditions (overcast/fog/freezing/storm) use one token for both. NOTE: these are
Open-Meteo WMO *interpretation* codes, deliberately mapped by hand from
Open-Meteo's documented list.
"""

from __future__ import annotations

from types import MappingProxyType
from typing import Final, Literal, TypedDict

# The closed set of semantic condition tokens this module can emit, day/night
# resolved. Making it a Literal (not a bare `str`) means the contract's `icon`
# fields carry a real, checkable vocabulary end to end: a new token MUST be added
# here, which is exactly the prompt to also map it in the icon pack. Keep in sync
# with `_WMO` + `_UNKNOWN`; mypy flags any drift. Neutral conditions carry a
# single token used for both day and night.
IconToken = Literal[
    "clear-day",
    "clear-night",
    "mostly-clear-day",
    "mostly-clear-night",
    "partly-cloudy-day",
    "partly-cloudy-night",
    "overcast",
    "fog",
    "drizzle-day",
    "drizzle-night",
    "freezing-drizzle",
    "rain-day",
    "rain-night",
    "freezing-rain",
    "snow-day",
    "snow-night",
    "showers-day",
    "showers-night",
    "snow-showers-day",
    "snow-showers-night",
    "thunderstorm",
    "not-available",
]


class Condition(TypedDict):
    icon: IconToken  # a semantic condition token, e.g. "rain-day"
    text: str  # short human label, e.g. "Light rain"


# code -> (day token, night token, label). Neutral conditions repeat the token.
_WMO: Final[dict[int, tuple[IconToken, IconToken, str]]] = {
    0: ("clear-day", "clear-night", "Clear"),
    1: ("mostly-clear-day", "mostly-clear-night", "Mainly clear"),
    2: ("partly-cloudy-day", "partly-cloudy-night", "Partly cloudy"),
    3: ("overcast", "overcast", "Overcast"),
    45: ("fog", "fog", "Fog"),
    48: ("fog", "fog", "Rime fog"),
    51: ("drizzle-day", "drizzle-night", "Light drizzle"),
    53: ("drizzle-day", "drizzle-night", "Drizzle"),
    55: ("drizzle-day", "drizzle-night", "Heavy drizzle"),
    56: ("freezing-drizzle", "freezing-drizzle", "Freezing drizzle"),
    57: ("freezing-drizzle", "freezing-drizzle", "Freezing drizzle"),
    61: ("rain-day", "rain-night", "Light rain"),
    63: ("rain-day", "rain-night", "Rain"),
    65: ("rain-day", "rain-night", "Heavy rain"),
    66: ("freezing-rain", "freezing-rain", "Freezing rain"),
    67: ("freezing-rain", "freezing-rain", "Freezing rain"),
    71: ("snow-day", "snow-night", "Light snow"),
    73: ("snow-day", "snow-night", "Snow"),
    75: ("snow-day", "snow-night", "Heavy snow"),
    77: ("snow-day", "snow-night", "Snow grains"),
    80: ("showers-day", "showers-night", "Light showers"),
    81: ("showers-day", "showers-night", "Showers"),
    82: ("showers-day", "showers-night", "Violent showers"),
    85: ("snow-showers-day", "snow-showers-night", "Snow showers"),
    86: ("snow-showers-day", "snow-showers-night", "Snow showers"),
    95: ("thunderstorm", "thunderstorm", "Thunderstorm"),
    96: ("thunderstorm", "thunderstorm", "Thunderstorm with hail"),
    99: ("thunderstorm", "thunderstorm", "Thunderstorm with hail"),
}

# Read-only view -> the table can't be mutated at runtime.
WMO: Final = MappingProxyType(_WMO)

_UNKNOWN: Final[tuple[IconToken, IconToken, str]] = (
    "not-available",
    "not-available",
    "Unknown",
)


def describe(code: int, is_day: bool = True) -> Condition:
    """Resolve a WMO code (+ day/night) to its condition token and label.

    Unknown codes fall back to the `not-available` token rather than raising, so
    a surprise code from the API can never break rendering.
    """
    day, night, label = _WMO.get(code, _UNKNOWN)
    return {"icon": day if is_day else night, "text": label}


# Codes that do NOT precipitate: clear (0), mainly clear (1), partly cloudy (2),
# overcast (3), fog (45), rime fog (48). Every other documented code is a
# drizzle/rain/snow/showers/thunderstorm family and DOES precipitate. Kept as the
# small dry set (not a large wet set) so a precip code added to `_WMO` later is
# wet by default - the mapping stays the single source of truth.
_DRY: Final[frozenset[int]] = frozenset({0, 1, 2, 3, 45, 48})


def is_wet(code: int) -> bool:
    """Whether a WMO code precipitates (rain OR snow) - gates the forecast card's
    precip-chance line. An unmapped code is treated as dry: we can't assert it
    precipitates, so we don't show a precip line for it.
    """
    return code in _WMO and code not in _DRY
