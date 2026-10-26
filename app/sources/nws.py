"""NWS station observation: the opt-in overlay on the hero's current conditions.

When `NWS_STATION` is set, the latest measured observation overlays the model's
current conditions per field (see `weather.merge_current`); the forecast is
untouched.

Payload: quantitative fields are `{value, unitCode, qualityControl}` objects
whose `value` is often null and whose keys can be absent, so every read is
defensive. Conversions key on `unitCode`; an unexpected unit makes the field
absent rather than converted wrongly.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Final

from app.config import settings
from app.http import build_session

log = logging.getLogger("pi_dashboard.nws")

_OBS_URL: Final = "https://api.weather.gov/stations/{station}/observations/latest"

_REQUEST_TIMEOUT_SECONDS: Final = 10

# The User-Agent is set once here, so changing it needs a process restart.
_SESSION: Final = build_session()
_SESSION.headers.update({"User-Agent": settings.nws_user_agent})

# NWS icon slug -> WMO code. Slugs with no honest analog (haze/smoke/dust,
# hot/cold, unknown future slugs) are deliberately absent: the hero then keeps
# the model's condition, so the overlay can correct it but never degrade it to
# not-available. Every value must exist in `weather_codes._WMO` (a test pins
# it). wind_* slugs share their base bucket - there is no windy WMO code.
_SLUG_TO_WMO: Final[dict[str, int]] = {
    "skc": 0,
    "few": 1,
    "sct": 2,
    "bkn": 3,  # broken ≈ mostly cloudy - nearest is the overcast bucket
    "ovc": 3,
    "wind_skc": 0,
    "wind_few": 1,
    "wind_sct": 2,
    "wind_bkn": 3,
    "wind_ovc": 3,
    "fog": 45,
    "rain": 63,
    "rain_showers": 80,
    "rain_showers_hi": 80,
    "tsra": 95,
    "tsra_sct": 95,
    "tsra_hi": 95,
    "snow": 73,
    "blizzard": 75,  # heavy snow - nearest
    "sleet": 77,  # snow grains - nearest non-freezing-rain ice bucket
    "rain_snow": 85,  # snow showers - nearest mixed bucket
    "rain_sleet": 85,
    "snow_sleet": 85,
    "fzra": 66,
    "rain_fzra": 66,
    "snow_fzra": 66,
    "tornado": 95,  # severe convective - nearest; hero text stays sane
    "hurricane": 95,
    "tropical_storm": 95,
}


@dataclass(frozen=True, slots=True)
class Observation:
    """Not a contract TypedDict: it never goes through the JSON cache. Numbers
    stay floats; rounding happens once, at the merge."""

    timestamp: datetime  # aware; feeds the staleness gate in merge_current
    temp_f: float | None
    heat_index_f: float | None
    wind_chill_f: float | None
    humidity_pct: float | None
    wind_mph: float | None
    wmo_code: int | None


def slug_to_wmo(slug: str) -> int | None:
    return _SLUG_TO_WMO.get(slug)


def parse_icon_slug(url: str | None) -> str | None:
    """The slug from `.../icons/land/{day|night}/{slug}`, or None. Dual-condition
    paths (`.../rain,40/tsra,60`) take the first; the `,{pct}` suffix is
    stripped."""
    if not url:
        return None
    segments = [s for s in url.split("?", 1)[0].split("/") if s]
    for marker in ("day", "night"):
        if marker in segments:
            rest = segments[segments.index(marker) + 1 :]
            if rest:
                return rest[0].split(",", 1)[0] or None
            return None
    return None


def _unit_name(unit_code: object) -> str | None:
    """Strip `wmoUnit:` (current) or `unit:` (legacy); any other prefix means
    the unit can't be trusted."""
    if not isinstance(unit_code, str):
        return None
    for prefix in ("wmoUnit:", "unit:"):
        if unit_code.startswith(prefix):
            return unit_code[len(prefix) :]
    return None


def _quantity(props: dict[str, Any], key: str) -> tuple[float, str] | None:
    """(value, bare unit), or None if absent, null, non-numeric, or unknown unit."""
    field = props.get(key)
    if not isinstance(field, dict):
        return None
    value = field.get("value")
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    unit = _unit_name(field.get("unitCode"))
    if unit is None:
        return None
    return float(value), unit


def _temp_f(props: dict[str, Any], key: str) -> float | None:
    q = _quantity(props, key)
    if q is None:
        return None
    value, unit = q
    if unit == "degC":
        return value * 9 / 5 + 32
    if unit == "degF":
        return value
    return None  # unexpected unit: absent beats converted wrongly


def _wind_mph(props: dict[str, Any], key: str) -> float | None:
    q = _quantity(props, key)
    if q is None:
        return None
    value, unit = q
    return value / 1.609344 if unit == "km_h-1" else None


def _percent(props: dict[str, Any], key: str) -> float | None:
    q = _quantity(props, key)
    if q is None:
        return None
    value, unit = q
    return value if unit == "percent" else None


def normalize_observation(raw: dict[str, Any]) -> Observation:
    """Bad fields become None. Raises only without `properties` or an aware
    timestamp - the staleness gate needs one."""
    props = raw.get("properties")
    if not isinstance(props, dict):
        raise ValueError("NWS observation missing 'properties'")
    ts_raw = props.get("timestamp")
    if not isinstance(ts_raw, str):
        raise ValueError(f"NWS observation timestamp unparseable: {ts_raw!r}")
    try:
        timestamp = datetime.fromisoformat(ts_raw)
    except ValueError as exc:
        raise ValueError(f"NWS observation timestamp unparseable: {ts_raw!r}") from exc
    if timestamp.tzinfo is None:
        raise ValueError(f"NWS observation timestamp lacks an offset: {ts_raw!r}")
    icon = props.get("icon")
    slug = parse_icon_slug(icon if isinstance(icon, str) else None)
    return Observation(
        timestamp=timestamp,
        temp_f=_temp_f(props, "temperature"),
        heat_index_f=_temp_f(props, "heatIndex"),
        wind_chill_f=_temp_f(props, "windChill"),
        humidity_pct=_percent(props, "relativeHumidity"),
        wind_mph=_wind_mph(props, "windSpeed"),
        wmo_code=slug_to_wmo(slug) if slug is not None else None,
    )


def _fetch_raw(station: str) -> dict[str, Any]:
    resp = _SESSION.get(
        _OBS_URL.format(station=station), timeout=_REQUEST_TIMEOUT_SECONDS
    )
    resp.raise_for_status()
    data: dict[str, Any] = resp.json()
    return data


async def fetch_observation(station: str) -> Observation | None:
    """None on any failure: a flaky api.weather.gov must degrade the hero to
    model conditions, never fail the weather tick."""
    try:
        raw = await asyncio.to_thread(_fetch_raw, station)
        return normalize_observation(raw)
    except Exception as exc:
        log.warning("NWS observation fetch failed for %s: %s", station, exc)
        return None
