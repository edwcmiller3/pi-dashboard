"""Open-Meteo WMO interpretation code -> condition token + label.

The frontend never sees raw WMO codes: it gets a day/night-resolved `IconToken`
(from Open-Meteo's `is_day`), which an icon pack maps to a glyph. Mapped by hand
from Open-Meteo's documented code list.
"""

from __future__ import annotations

from types import MappingProxyType
from typing import Final, Literal, TypedDict

# A new token added here must also be mapped in every icon pack (mypy flags a
# pack that misses it). Neutral conditions use one token for day and night.
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
    icon: IconToken
    text: str  # e.g. "Light rain"


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

WMO: Final = MappingProxyType(_WMO)

_UNKNOWN: Final[tuple[IconToken, IconToken, str]] = (
    "not-available",
    "not-available",
    "Unknown",
)


def describe(code: int, is_day: bool = True) -> Condition:
    """Unknown codes fall back to `not-available` so a surprise code from the
    API can't break rendering."""
    day, night, label = _WMO.get(code, _UNKNOWN)
    return {"icon": day if is_day else night, "text": label}


# Clear / cloudy / fog. Listed as the dry set so a code added to `_WMO` later is
# wet by default.
_DRY: Final[frozenset[int]] = frozenset({0, 1, 2, 3, 45, 48})


def is_wet(code: int) -> bool:
    """Whether a code precipitates (gates the forecast precip line). Unmapped
    codes count as dry."""
    return code in _WMO and code not in _DRY
