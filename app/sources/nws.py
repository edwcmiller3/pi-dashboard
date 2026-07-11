"""NWS station-observation source — the opt-in current-conditions overlay.

A station *measures* the weather; a forecast model only *estimates* it. When
`NWS_STATION` is set, the latest observation from that station overlays the
hero's current conditions per-field (see `weather.merge_current`); the
Open-Meteo forecast is untouched. Empty station = this module is never called.

Same pure/impure split as `weather`:
  * `parse_icon_slug` / `slug_to_wmo` / `normalize_observation` — pure:
    raw NWS GeoJSON -> `Observation`.
  * `fetch_observation` — impure: the single api.weather.gov call, offloaded
    via `asyncio.to_thread`. It swallows EVERY failure (network, HTTP,
    malformed payload) into `None` + one warning — the overlay must never
    fail the weather tick; api.weather.gov is known to be occasionally flaky.

Payload facts (verified live 2026-07-11): everything lives under `properties`;
quantitative fields are `{value, unitCode, qualityControl}` objects whose
`value` is frequently null, and whole keys can be absent — so every read is
`.get()` + defaults. Units are SI (`wmoUnit:degC`, `wmoUnit:km_h-1`);
conversions are keyed on `unitCode`, and an unexpected unit makes the field
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

# Pooled session (see app.http). api.weather.gov requires a User-Agent and asks
# that it carry contact info — set once at build time from settings, which means
# a UA change needs a process restart (same lifecycle as the session itself).
_SESSION: Final = build_session()
_SESSION.headers.update({"User-Agent": settings.nws_user_agent})

# NWS icon-slug -> Open-Meteo WMO interpretation code. Fail-soft by design: a
# slug absent here (haze/smoke/dust have no honest WMO analog in our table;
# hot/cold are temperature statements, not sky conditions; unknown future slugs)
# returns None and the hero keeps the MODEL's condition triple while the
# observation's numbers still apply — the overlay can only ever *correct* the
# condition, never coarsen it to wi-na or mislabel. Every code on the right MUST
# exist in `weather_codes._WMO` (a test pins that invariant). The wind_* slugs
# share their base slug's bucket: there is no windy WMO code, and the wind
# number shows separately on the hero anyway.
_SLUG_TO_WMO: Final[dict[str, int]] = {
    "skc": 0,
    "few": 1,
    "sct": 2,
    "bkn": 3,  # broken ≈ mostly cloudy — nearest is the overcast bucket
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
    "blizzard": 75,  # heavy snow — nearest
    "sleet": 77,  # snow grains — nearest non-freezing-rain ice bucket
    "rain_snow": 85,  # snow showers — nearest mixed bucket
    "rain_sleet": 85,
    "snow_sleet": 85,
    "fzra": 66,
    "rain_fzra": 66,
    "snow_fzra": 66,
    "tornado": 95,  # severe convective — nearest; hero text stays sane
    "hurricane": 95,
    "tropical_storm": 95,
}


@dataclass(frozen=True, slots=True)
class Observation:
    """One normalized station observation. A frozen dataclass, not a contract
    TypedDict: it never round-trips through the JSON cache (the TypedDict
    rationale in `contract.py` doesn't apply) and immutability suits the pure
    merge. Numbers stay floats — rounding happens once, at the merge edge."""

    timestamp: datetime  # aware; feeds the staleness gate in merge_current
    temp_f: float | None
    heat_index_f: float | None
    wind_chill_f: float | None
    humidity_pct: float | None
    wind_mph: float | None
    wmo_code: int | None


def slug_to_wmo(slug: str) -> int | None:
    """Map an NWS icon slug to a WMO code, or None when there is no honest
    analog — the caller then keeps the model's condition (fail-soft)."""
    return _SLUG_TO_WMO.get(slug)


def parse_icon_slug(url: str | None) -> str | None:
    """The condition slug embedded in an NWS icon URL, or None.

    URLs look like `https://api.weather.gov/icons/land/{day|night}/{slug}` with
    two documented twists parsed defensively here: dual-condition paths
    (`.../rain,40/tsra,60` — first segment wins) and a `,{pct}` coverage suffix
    (stripped). Anything unrecognizable is None, never an exception.
    """
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
    """Strip the unit-namespace prefix (`wmoUnit:` current, `unit:` legacy) —
    conversions key on the bare name and an unrecognized prefix means the
    field's unit can't be trusted."""
    if not isinstance(unit_code, str):
        return None
    for prefix in ("wmoUnit:", "unit:"):
        if unit_code.startswith(prefix):
            return unit_code[len(prefix) :]
    return None


def _quantity(props: dict[str, Any], key: str) -> tuple[float, str] | None:
    """A quantitative field's (value, bare unit name), or None when the key is
    absent, the value is null/non-numeric, or the unit is unrecognizable."""
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
    """Raw NWS observation GeoJSON -> `Observation` (pure).

    Individual missing/null/wrong-unit fields are just None (per-field
    fail-soft). Only a structurally hopeless payload raises: no `properties`,
    or a timestamp that can't parse to an aware datetime — without one the
    staleness gate can't run, so the whole observation is unusable.
    """
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
    """The blocking api.weather.gov call (runs in a worker thread)."""
    resp = _SESSION.get(
        _OBS_URL.format(station=station), timeout=_REQUEST_TIMEOUT_SECONDS
    )
    resp.raise_for_status()
    data: dict[str, Any] = resp.json()
    return data


async def fetch_observation(station: str) -> Observation | None:
    """Fetch + normalize the station's latest observation, or None on ANY
    failure. The overlay is strictly optional: a flaky api.weather.gov must
    degrade the hero to pure-model conditions, never fail the weather tick.
    """
    try:
        raw = await asyncio.to_thread(_fetch_raw, station)
        return normalize_observation(raw)
    except Exception as exc:
        log.warning("NWS observation fetch failed for %s: %s", station, exc)
        return None
