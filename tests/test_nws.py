"""NWS observation-overlay tests.

Covers the pure surface of `app.sources.nws` — the icon-slug → WMO map, the
defensive icon-URL parser, and `normalize_observation` — plus the pure
`merge_current` overlay in `app.sources.weather` and the swallow-everything
behavior of the impure `fetch_observation`.

Fixtures are live captures from api.weather.gov on 2026-07-11 (public station
data, no PII), trimmed to the `properties` fields the adapter reads plus a few
bystanders for realism. Quantitative fields are `{value, unitCode,
qualityControl}` objects; `value` is frequently null and WHOLE KEYS can be
absent — both verified live (KOQT returned no `relativeHumidity` variant and a
null `icon` on capture day).
"""

from __future__ import annotations

import asyncio
import copy
import logging
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from typing import Any

import pytest
from conftest import current_weather

from app.sources import nws, weather
from app.sources.nws import Observation
from app.weather_codes import WMO

# Live capture: KTYS 2026-07-11T16:45:00+00:00 — a "healthy" observation with
# an icon URL and a live heatIndex (windChill null, as expected in July).
FULL_OBS: dict[str, Any] = {
    "id": "https://api.weather.gov/stations/KTYS/observations/2026-07-11T16:45:00+00:00",
    "type": "Feature",
    "properties": {
        "@id": "https://api.weather.gov/stations/KTYS/observations/2026-07-11T16:45:00+00:00",
        "@type": "wx:ObservationStation",
        "station": "https://api.weather.gov/stations/KTYS",
        "stationId": "KTYS",
        "timestamp": "2026-07-11T16:45:00+00:00",
        "textDescription": "Mostly Cloudy",
        "icon": "https://api.weather.gov/icons/land/day/bkn?size=medium",
        "temperature": {"unitCode": "wmoUnit:degC", "value": 28, "qualityControl": "V"},
        "dewpoint": {"unitCode": "wmoUnit:degC", "value": 20, "qualityControl": "V"},
        "windSpeed": {
            "unitCode": "wmoUnit:km_h-1",
            "value": 20.376,
            "qualityControl": "V",
        },
        "windGust": {
            "unitCode": "wmoUnit:km_h-1",
            "value": None,
            "qualityControl": "Z",
        },
        "relativeHumidity": {
            "unitCode": "wmoUnit:percent",
            "value": 61.837259550781,
            "qualityControl": "V",
        },
        "windChill": {"unitCode": "wmoUnit:degC", "value": None, "qualityControl": "V"},
        "heatIndex": {
            "unitCode": "wmoUnit:degC",
            "value": 29.65712540116,
            "qualityControl": "V",
        },
    },
}

# Live capture: KOQT 2026-07-11T15:53:00+00:00 — a sparse observation: null
# `icon`, empty `textDescription`, null `windChill`, and windSpeed of exactly 0
# (a real reading — must NOT be treated as missing). Hand-modified from the
# capture: `heatIndex` value nulled and the `relativeHumidity` key REMOVED
# entirely (the live payload had both) so the fixture pins both the
# null-value and the absent-key branches.
SPARSE_OBS: dict[str, Any] = {
    "id": "https://api.weather.gov/stations/KOQT/observations/2026-07-11T15:53:00+00:00",
    "type": "Feature",
    "properties": {
        "@id": "https://api.weather.gov/stations/KOQT/observations/2026-07-11T15:53:00+00:00",
        "@type": "wx:ObservationStation",
        "station": "https://api.weather.gov/stations/KOQT",
        "stationId": "KOQT",
        "timestamp": "2026-07-11T15:53:00+00:00",
        "textDescription": "",
        "icon": None,
        "temperature": {
            "unitCode": "wmoUnit:degC",
            "value": 27.2,
            "qualityControl": "V",
        },
        "windSpeed": {"unitCode": "wmoUnit:km_h-1", "value": 0, "qualityControl": "V"},
        "windChill": {"unitCode": "wmoUnit:degC", "value": None, "qualityControl": "V"},
        "heatIndex": {"unitCode": "wmoUnit:degC", "value": None, "qualityControl": "V"},
    },
}

# Structurally hopeless payload — no `properties` at all.
GARBAGE: dict[str, Any] = {"type": "Feature", "detail": "not an observation"}


def with_properties(**overrides: Any) -> dict[str, Any]:
    """A copy of FULL_OBS with `properties` fields overridden (same idea as
    test_weather's `with_current`)."""
    return {**FULL_OBS, "properties": {**FULL_OBS["properties"], **overrides}}


# ── slug_to_wmo: the fail-soft NWS icon-slug → WMO map ────────────────────────


@pytest.mark.parametrize(
    ("slug", "code"),
    [
        ("skc", 0),
        ("few", 1),
        ("sct", 2),
        ("bkn", 3),  # broken ≈ mostly cloudy — judgment call: overcast glyph
        ("ovc", 3),
        ("wind_skc", 0),  # wind_* variants: same bucket as the base slug —
        ("wind_few", 1),  # no windy WMO bucket; the wind number shows separately
        ("wind_sct", 2),
        ("wind_bkn", 3),
        ("wind_ovc", 3),
        ("fog", 45),
        ("rain", 63),
        ("rain_showers", 80),
        ("rain_showers_hi", 80),
        ("tsra", 95),
        ("tsra_sct", 95),
        ("tsra_hi", 95),
        ("snow", 73),
        ("blizzard", 75),  # heavy snow — nearest
        ("sleet", 77),  # snow grains — nearest non-freezing-rain ice bucket
        ("rain_snow", 85),  # snow showers — nearest mixed bucket
        ("rain_sleet", 85),
        ("snow_sleet", 85),
        ("fzra", 66),
        ("rain_fzra", 66),
        ("snow_fzra", 66),
        ("tornado", 95),  # severe convective — nearest; hero text stays sane
        ("hurricane", 95),
        ("tropical_storm", 95),
    ],
)
def test_slug_to_wmo_mapped(slug: str, code: int) -> None:
    assert nws.slug_to_wmo(slug) == code


@pytest.mark.parametrize(
    "slug",
    [
        "haze",  # no honest WMO analog — mislabeling as "Fog" would lie
        "smoke",
        "dust",
        "hot",  # temperature statements, not sky conditions
        "cold",
        "some_future_slug",  # forward-compatible: unknown falls back, never crashes
        "",
    ],
)
def test_slug_to_wmo_unmapped_is_none(slug: str) -> None:
    assert nws.slug_to_wmo(slug) is None


def test_every_mapped_code_resolves_to_a_real_glyph() -> None:
    # Invariant: the overlay must never introduce a code that
    # `describe()` can't resolve — every mapped code exists in the WMO table,
    # so the hero can never show wi-na/"Unknown" because of NWS.
    for slug, code in nws._SLUG_TO_WMO.items():
        assert code in WMO, f"slug {slug!r} maps to {code}, not in weather_codes.WMO"


# ── parse_icon_slug: defensive icon-URL parsing ───────────────────────────────


@pytest.mark.parametrize(
    ("url", "slug"),
    [
        ("https://api.weather.gov/icons/land/day/bkn?size=medium", "bkn"),
        ("https://api.weather.gov/icons/land/night/skc?size=medium", "skc"),
        # dual-condition URL: first segment wins
        ("https://api.weather.gov/icons/land/day/rain,40/tsra,60?size=medium", "rain"),
        # `,{pct}` suffix stripped from a single-condition slug too
        ("https://api.weather.gov/icons/land/night/tsra_hi,80?size=medium", "tsra_hi"),
        ("https://api.weather.gov/icons/land/day/rain_showers", "rain_showers"),
    ],
)
def test_parse_icon_slug(url: str, slug: str) -> None:
    assert nws.parse_icon_slug(url) == slug


@pytest.mark.parametrize(
    "url",
    [
        None,
        "",
        "https://api.weather.gov/icons/land/day/",  # nothing after day segment
        "https://example.com/not/an/icon/url",  # no day|night marker
        "garbage",
    ],
)
def test_parse_icon_slug_malformed_is_none(url: str | None) -> None:
    assert nws.parse_icon_slug(url) is None


# ── normalize_observation: raw GeoJSON → Observation ─────────────────────────


def test_full_observation_converts_units_exactly() -> None:
    obs = nws.normalize_observation(FULL_OBS)
    assert obs.timestamp == datetime(2026, 7, 11, 16, 45, tzinfo=timezone.utc)
    assert obs.temp_f == 28 * 9 / 5 + 32  # 82.4 °F
    assert obs.heat_index_f == 29.65712540116 * 9 / 5 + 32  # ≈ 85.38 °F
    assert obs.wind_chill_f is None  # null value in the feed
    assert obs.humidity_pct == 61.837259550781  # percent passes through unscaled
    assert obs.wind_mph == 20.376 / 1.609344  # km/h → mph, ≈ 12.66
    assert obs.wmo_code == 3  # icon slug "bkn"


def test_sparse_observation_yields_nones_without_raising() -> None:
    obs = nws.normalize_observation(SPARSE_OBS)
    assert obs.temp_f == 27.2 * 9 / 5 + 32  # 80.96 °F
    assert obs.wind_mph == 0.0  # a real zero reading — NOT missing
    assert obs.humidity_pct is None  # whole key absent
    assert obs.heat_index_f is None  # null value
    assert obs.wind_chill_f is None
    assert obs.wmo_code is None  # icon is null


@pytest.mark.parametrize(
    ("field", "payload"),
    [
        # unexpected unit → field treated as absent, never converted wrongly
        ("temperature", {"unitCode": "wmoUnit:K", "value": 300.0}),
        ("windSpeed", {"unitCode": "wmoUnit:m_s-1", "value": 5.0}),
        ("relativeHumidity", {"unitCode": "wmoUnit:degC", "value": 50.0}),
        # missing unitCode entirely
        ("temperature", {"value": 28.0}),
        # value that isn't a number
        ("temperature", {"unitCode": "wmoUnit:degC", "value": "28"}),
    ],
)
def test_wrong_or_unknown_unit_makes_the_field_none(
    field: str, payload: dict[str, Any]
) -> None:
    obs = nws.normalize_observation(with_properties(**{field: payload}))
    attr = {
        "temperature": "temp_f",
        "windSpeed": "wind_mph",
        "relativeHumidity": "humidity_pct",
    }[field]
    assert getattr(obs, attr) is None


def test_legacy_unit_prefix_accepted() -> None:
    # NWS has used both "wmoUnit:" and legacy "unit:" prefixes — accept both.
    obs = nws.normalize_observation(
        with_properties(temperature={"unitCode": "unit:degC", "value": 28})
    )
    assert obs.temp_f == 28 * 9 / 5 + 32


def test_garbage_payload_raises_clear_valueerror() -> None:
    with pytest.raises(ValueError, match="properties"):
        nws.normalize_observation(GARBAGE)


@pytest.mark.parametrize("timestamp", [None, "not-a-time", ""])
def test_unparseable_timestamp_raises_clear_valueerror(timestamp: str | None) -> None:
    # Without an aware timestamp the staleness gate can't run — structurally
    # hopeless, so raise (the impure fetch turns it into a fail-soft None).
    with pytest.raises(ValueError, match="timestamp"):
        nws.normalize_observation(with_properties(timestamp=timestamp))


# ── merge_current: pure per-field overlay in app.sources.weather ──────────────

_NOW = datetime(2026, 7, 11, 17, 0, tzinfo=timezone.utc)


def _obs(**overrides: Any) -> Observation:
    """A fresh, fully-populated Observation; override per test."""
    base = Observation(
        timestamp=_NOW - timedelta(minutes=10),
        temp_f=82.4,
        heat_index_f=85.4,
        wind_chill_f=None,
        humidity_pct=61.8,
        wind_mph=12.7,
        wmo_code=3,
    )
    return replace(base, **overrides)


def test_merge_obs_numbers_win_and_round_half_up() -> None:
    model = current_weather(temp_f=75)
    merged = weather.merge_current(model, _obs(temp_f=72.5, wind_mph=6.5), _NOW)
    assert merged["temp_f"] == 73  # 72.5 rounds UP, not banker's
    assert merged["wind_mph"] == 7
    assert merged["humidity_pct"] == 62  # 61.8 -> 62
    assert merged["feels_like_f"] == 85  # heatIndex 85.4 -> 85


@pytest.mark.parametrize(
    ("obs_field", "model_field"),
    [
        ("temp_f", "temp_f"),
        ("humidity_pct", "humidity_pct"),
        ("wind_mph", "wind_mph"),
    ],
)
def test_merge_none_obs_field_keeps_model_value(
    obs_field: str, model_field: str
) -> None:
    # Per-field fallback: a station that didn't report a field only loses THAT
    # field to the model, not the whole observation.
    model = current_weather(temp_f=75)
    merged = weather.merge_current(model, _obs(**{obs_field: None}), _NOW)
    assert merged[model_field] == model[model_field]  # type: ignore[literal-required]


def test_merge_stale_observation_returns_model_unchanged() -> None:
    # >90 min old: discard the whole observation rather than show a confidently
    # wrong "now". Result equals the input model but is NOT the same (possibly
    # mutated) object — pins that merge_current never mutates its input.
    model = current_weather(temp_f=75)
    snapshot = copy.deepcopy(model)
    stale = _obs(timestamp=_NOW - timedelta(minutes=91))
    merged = weather.merge_current(model, stale, _NOW)
    assert merged == snapshot
    assert merged is not model
    assert model == snapshot  # input never mutated


def test_merge_observation_exactly_at_the_gate_still_applies() -> None:
    # The gate is `> 90 min`; exactly 90 is still acceptable (stations report
    # hourly — 90 min means at most one missed cycle).
    model = current_weather(temp_f=75)
    at_gate = _obs(timestamp=_NOW - timedelta(minutes=90))
    assert weather.merge_current(model, at_gate, _NOW)["temp_f"] == 82


def test_merge_feels_like_prefers_heat_index() -> None:
    model = current_weather(temp_f=75)
    merged = weather.merge_current(
        model, _obs(heat_index_f=88.2, wind_chill_f=None), _NOW
    )
    assert merged["feels_like_f"] == 88


def test_merge_feels_like_falls_back_to_wind_chill() -> None:
    model = current_weather(temp_f=75)
    merged = weather.merge_current(
        model, _obs(temp_f=40.0, heat_index_f=None, wind_chill_f=33.6), _NOW
    )
    assert merged["feels_like_f"] == 34


def test_merge_feels_like_ends_at_obs_temp_never_the_model() -> None:
    # NWS nulls heatIndex/windChill exactly when neither applies — feels-like ≈
    # temp then. Falling back to the MODEL's apparent_temperature could pair a
    # model feels-like with an obs temp several °F apart (incoherent hero).
    model = current_weather(temp_f=75)  # model feels_like_f == 75
    merged = weather.merge_current(
        model, _obs(temp_f=68.4, heat_index_f=None, wind_chill_f=None), _NOW
    )
    assert merged["feels_like_f"] == 68  # obs temp, NOT the model's 75


def test_merge_feels_like_all_none_keeps_model() -> None:
    # Nothing observed at all (temp included) — only then does the model's
    # feels-like stand, consistent with per-field fallback.
    model = current_weather(temp_f=75)
    merged = weather.merge_current(
        model, _obs(temp_f=None, heat_index_f=None, wind_chill_f=None), _NOW
    )
    assert merged["feels_like_f"] == model["feels_like_f"]


def test_merge_mapped_condition_swaps_code_text_icon_honoring_model_is_day() -> None:
    model = current_weather(temp_f=75)
    model["is_day"] = False  # night per the model's clock-derived flag
    merged = weather.merge_current(model, _obs(wmo_code=63), _NOW)
    assert merged["code"] == 63
    assert merged["text"] == "Rain"
    assert merged["icon"] == "wi-night-alt-rain"  # night variant — is_day honored
    assert merged["is_day"] is False


def test_merge_unmappable_condition_keeps_model_triple_but_numbers_merge() -> None:
    # An unmappable/missing NWS icon must keep
    # the MODEL's condition (preserving the WMO code richness — never wi-na or
    # a mislabel) while the observation's numbers still apply.
    model = current_weather(temp_f=75)  # code 0 / "Clear" / wi-day-sunny
    merged = weather.merge_current(model, _obs(wmo_code=None, temp_f=82.4), _NOW)
    assert merged["code"] == model["code"]
    assert merged["text"] == model["text"]
    assert merged["icon"] == model["icon"]
    assert merged["temp_f"] == 82  # numbers still merged


@pytest.mark.parametrize(
    "field", ["precip_prob_pct", "high_f", "low_f", "sunrise", "sunset", "is_day"]
)
def test_merge_model_only_fields_never_change(field: str) -> None:
    # Forecast/astronomical/clock concepts a station can't measure.
    model = current_weather(temp_f=75)
    merged = weather.merge_current(model, _obs(), _NOW)
    assert merged[field] == model[field]  # type: ignore[literal-required]


def test_merge_returns_a_new_dict_and_never_mutates_the_model() -> None:
    model = current_weather(temp_f=75)
    snapshot = copy.deepcopy(model)
    merged = weather.merge_current(model, _obs(), _NOW)
    assert merged is not model
    assert model == snapshot


# ── fetch_observation: impure wrapper swallows everything ─────────────────────


def test_fetch_observation_swallows_failures_and_warns(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    # The overlay must NEVER fail the weather tick: any exception — network,
    # HTTP, malformed payload — degrades to None plus one warning log.
    def _boom(station: str) -> dict[str, Any]:
        raise ConnectionError("api.weather.gov unreachable")

    monkeypatch.setattr(nws, "_fetch_raw", _boom)
    with caplog.at_level(logging.WARNING):
        result = asyncio.run(nws.fetch_observation("KXYZ"))
    assert result is None
    assert any("KXYZ" in r.message for r in caplog.records)
    assert any(r.levelno == logging.WARNING for r in caplog.records)


def test_fetch_observation_normalize_failure_also_degrades_to_none(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    monkeypatch.setattr(nws, "_fetch_raw", lambda station: GARBAGE)
    with caplog.at_level(logging.WARNING):
        result = asyncio.run(nws.fetch_observation("KXYZ"))
    assert result is None


def test_fetch_observation_returns_normalized_observation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(nws, "_fetch_raw", lambda station: FULL_OBS)
    result = asyncio.run(nws.fetch_observation("KTYS"))
    assert result is not None
    assert result.wmo_code == 3
