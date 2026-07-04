"""Refresh-loop orchestration: TTL-gated cadence, per-source last-good
fallback, clock-honesty, and failure backoff.

The pure helpers (`_is_due`, `_backoff_delay`, `_clock_synced`) are tested
directly; `_refresh_once` is exercised with the source coroutines faked and the
cache redirected to a tmp dir (autouse `_tmp_cache` fixture), so the suite makes
no network call and writes only under `tmp_path`.

Source fakes are built through the typed `_weather_block`/`_calendar_block`
factories (real `WeatherBlock`/`CalendarBlock`, not `dict[str, Any]`) so a fake
that drifts from the contract fails the type-check. `Recorder` replaces the old
hand-rolled `calls = {...}` mutable-dict counting with a declarative call count.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Generic, TypeVar
from zoneinfo import ZoneInfo

import pytest

from app import cache, main
from app.config import settings
from app.contract import CalendarBlock, CurrentWeather, SourceBlock, WeatherBlock

TZ = ZoneInfo("America/New_York")
NOW = datetime(2026, 7, 1, 9, 0, tzinfo=TZ)

T = TypeVar("T")


def _stamp(dt: datetime) -> str:
    return dt.isoformat(timespec="seconds")


# ── typed source-block factories ─────────────────────────────────────────────


def _current(temp_f: int) -> CurrentWeather:
    return {
        "temp_f": temp_f,
        "feels_like_f": temp_f,
        "code": 0,
        "text": "Clear",
        "icon": "wi-day-sunny",
        "is_day": True,
        "humidity_pct": 50,
        "wind_mph": 5,
        "precip_prob_pct": 0,
        "high_f": temp_f + 5,
        "low_f": temp_f - 5,
        "sunrise": "2026-07-01T06:00:00-04:00",
        "sunset": "2026-07-01T20:00:00-04:00",
    }


def _weather_block(
    *,
    temp_f: int,
    fetched_at: str | None,
    ok: bool = True,
    ttl: int | None = None,
    attempted_at: str | None = None,
) -> WeatherBlock:
    block: WeatherBlock = {
        "ok": ok,
        "fetched_at": fetched_at,
        "current": _current(temp_f),
        "forecast": [],
    }
    if ttl is not None:
        block["ttl"] = ttl
    if attempted_at is not None:
        block["attempted_at"] = attempted_at
    return block


def _calendar_block(
    *,
    fetched_at: str | None,
    ok: bool = True,
    ttl: int | None = None,
    attempted_at: str | None = None,
) -> CalendarBlock:
    block: CalendarBlock = {"ok": ok, "fetched_at": fetched_at, "events": []}
    if ttl is not None:
        block["ttl"] = ttl
    if attempted_at is not None:
        block["attempted_at"] = attempted_at
    return block


class Recorder(Generic[T]):
    """A callable that returns a fixed typed result and counts its invocations —
    the declarative stand-in for the old `calls = {"weather": 0}` mutable-dict
    counting (like `unittest.mock.Mock.call_count`, but strongly typed)."""

    def __init__(self, result: T) -> None:
        self._result = result
        self.calls = 0

    def __call__(self, *args: object, **kwargs: object) -> T:
        self.calls += 1
        return self._result


def _patch_sources(
    monkeypatch: pytest.MonkeyPatch,
    *,
    weather: Callable[[], WeatherBlock],
    calendar: Callable[..., CalendarBlock],
) -> None:
    """Replace the two source coroutines. `weather`/`calendar` are callables
    returning the block (or raising) — invoked with no args / the kwargs main
    passes."""

    async def fake_weather() -> WeatherBlock:
        return weather()

    async def fake_calendar(
        now: datetime | None = None, last_good: CalendarBlock | None = None
    ) -> CalendarBlock:
        return calendar(last_good)

    monkeypatch.setattr(main, "get_weather", fake_weather)
    monkeypatch.setattr(main, "get_calendar", fake_calendar)


def _seed_cache(
    *,
    weather: WeatherBlock,
    calendar: CalendarBlock,
    generated_at: str | None = None,
) -> None:
    """Seed the cache with a prior doc. Deliberately a loose dict, not a full
    `DashboardDoc`: it models a previously-cached doc that may predate a field
    (e.g. `generated_at`), which is exactly what `_refresh_once` must tolerate."""
    doc: dict[str, Any] = {"weather": weather, "calendar": calendar}
    if generated_at is not None:
        doc["generated_at"] = generated_at
    cache.write(main._CACHE_KEY, doc)


# ── _is_due: TTL-gated cadence ───────────────────────────────────────────────


def test_is_due_when_no_prior_block() -> None:
    assert main._is_due(None, ttl=900, now=NOW, force=False, retry_floor=30) is True


def test_is_due_when_forced_even_if_fresh() -> None:
    fresh: SourceBlock = {"ok": True, "fetched_at": _stamp(NOW)}
    assert main._is_due(fresh, ttl=900, now=NOW, force=True, retry_floor=30) is True


def test_is_due_false_when_fresh_within_ttl() -> None:
    fresh: SourceBlock = {
        "ok": True,
        "fetched_at": _stamp(NOW - timedelta(seconds=300)),
    }
    assert main._is_due(fresh, ttl=900, now=NOW, force=False, retry_floor=30) is False


def test_is_due_true_when_aged_beyond_ttl() -> None:
    old: SourceBlock = {"ok": True, "fetched_at": _stamp(NOW - timedelta(seconds=1200))}
    assert main._is_due(old, ttl=900, now=NOW, force=False, retry_floor=30) is True


def test_is_due_true_when_fetched_at_missing_or_unparseable() -> None:
    miss: SourceBlock = {"ok": True, "fetched_at": None}
    junk: SourceBlock = {"ok": True, "fetched_at": "garbage"}
    assert main._is_due(miss, 900, NOW, False, retry_floor=30) is True
    assert main._is_due(junk, 900, NOW, False, retry_floor=30) is True


# ── _is_due: failed-source retry is rate-limited (no-hammer) ──────────────────


def test_is_due_failed_source_not_due_within_retry_floor() -> None:
    # The no-hammer guard: a source that failed 10s ago must NOT be retried while
    # the loop is in fast backoff — only once retry_floor has elapsed.
    failed: SourceBlock = {
        "ok": False,
        "fetched_at": None,
        "attempted_at": _stamp(NOW - timedelta(seconds=10)),
    }
    assert main._is_due(failed, ttl=900, now=NOW, force=False, retry_floor=30) is False


def test_is_due_failed_source_due_after_retry_floor() -> None:
    failed: SourceBlock = {
        "ok": False,
        "fetched_at": None,
        "attempted_at": _stamp(NOW - timedelta(seconds=40)),
    }
    assert main._is_due(failed, ttl=900, now=NOW, force=False, retry_floor=30) is True


def test_is_due_failed_source_rate_limit_uses_last_attempt_not_last_success() -> None:
    # A block whose last SUCCESS is ancient but was just RE-attempted must stay
    # rate-limited: attempted_at (not the stale fetched_at) governs the retry.
    failed: SourceBlock = {
        "ok": False,
        "fetched_at": _stamp(NOW - timedelta(hours=5)),  # last success, ancient
        "attempted_at": _stamp(NOW - timedelta(seconds=5)),  # just tried, failed
    }
    assert main._is_due(failed, ttl=900, now=NOW, force=False, retry_floor=900) is False


def test_is_due_failed_source_without_attempted_at_falls_back_to_fetched_at() -> None:
    # A failed block written before attempted_at existed rate-limits off fetched_at.
    failed: SourceBlock = {
        "ok": False,
        "fetched_at": _stamp(NOW - timedelta(seconds=5)),
    }
    assert main._is_due(failed, ttl=900, now=NOW, force=False, retry_floor=30) is False


# ── _backoff_delay: retry sooner after a failure, capped at base ─────────────


def test_backoff_grows_then_caps_at_base() -> None:
    base = 900
    # 30, 60, 120, 240, 480, then capped at base (900).
    assert main._backoff_delay(1, base) == 30
    assert main._backoff_delay(2, base) == 60
    assert main._backoff_delay(3, base) == 120
    assert main._backoff_delay(4, base) == 240
    # The growth->cap boundary: failure 5 is the last uncapped step (480 < 900),
    # failure 6 is the first the min() clamps (960 -> 900). This is exactly where
    # an off-by-one in `<< (failures - 1)` would hide, so pin both sides.
    assert main._backoff_delay(5, base) == 480
    assert main._backoff_delay(6, base) == base
    assert main._backoff_delay(99, base) == base  # never exceeds the base tick


# ── day rollover: window must roll at local midnight ─────────────────────────


def test_date_rolled_detects_local_day_change() -> None:
    assert main._date_rolled(_stamp(NOW - timedelta(days=1)), NOW) is True
    assert main._date_rolled(_stamp(NOW - timedelta(hours=2)), NOW) is False  # same day
    assert main._date_rolled(None, NOW) is False  # cold boot
    assert main._date_rolled("garbage", NOW) is False  # unparseable


def test_seconds_to_next_local_midnight() -> None:
    # NOW = 2026-07-01 09:00 EDT -> 15h until the next local midnight.
    assert main._seconds_to_next_local_midnight(NOW) == 15 * 3600


def test_seconds_to_next_local_midnight_across_spring_forward() -> None:
    # 2026-03-08 is US spring-forward (02:00 EST -> 03:00 EDT), so that local day
    # is only 23h long. From 00:30 EST the next local midnight (03-09 00:00 EDT)
    # is 22.5h away, NOT the 23.5h a naive wall-clock delta would give — the lost
    # hour must be accounted for. Guards the DST correctness of the .replace()
    # arithmetic, which the single-instant EDT case above can't exercise.
    now = datetime(2026, 3, 8, 0, 30, tzinfo=TZ)
    assert main._seconds_to_next_local_midnight(now) == 22.5 * 3600


# ── _clock_synced: honest about an unsynced Pi clock ─────────────────────────


def test_clock_synced_true_when_marker_present(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    marker = tmp_path / "synchronized"
    marker.write_text("", encoding="utf-8")
    monkeypatch.setattr(main, "_TIMESYNC_MARKER", marker)
    assert main._clock_synced() is True


def test_clock_synced_false_when_runtime_present_but_marker_absent(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    # timesyncd runtime dir exists (a Pi mid-boot) but NTP hasn't synced yet.
    # Create the runtime dir EXPLICITLY so the precondition (parent present,
    # marker absent) is stated by the test, not inherited from tmp_path existing.
    runtime = tmp_path / "timesync"
    runtime.mkdir()
    monkeypatch.setattr(main, "_TIMESYNC_MARKER", runtime / "synchronized")
    assert main._clock_synced() is False


def test_clock_synced_true_when_no_timesync_runtime(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    # Non-systemd host (the dev Mac): can't determine -> assume synced, don't nag.
    monkeypatch.setattr(main, "_TIMESYNC_MARKER", tmp_path / "absent" / "synchronized")
    assert main._clock_synced() is True


# ── _refresh_once: assembly, last-good, TTL gating, force ─────────────────────


def test_refresh_once_assembles_doc_with_ttls_and_clock(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "weather_ttl_seconds", 3600)
    monkeypatch.setattr(settings, "calendar_ttl_seconds", 900)
    monkeypatch.setattr(main, "_clock_synced", lambda: True)
    _patch_sources(
        monkeypatch,
        weather=Recorder(_weather_block(temp_f=72, fetched_at=_stamp(NOW))),
        calendar=Recorder(_calendar_block(fetched_at=_stamp(NOW))),
    )

    healthy = asyncio.run(main._refresh_once(now=NOW))
    assert healthy is True
    doc = cache.read(main._CACHE_KEY)
    assert doc is not None
    assert doc["clock_synced"] is True
    assert "generated_at" in doc
    assert doc["weather"]["ttl"] == 3600  # stamped per-source for the contract
    assert doc["calendar"]["ttl"] == 900
    assert doc["weather"]["current"]["temp_f"] == 72


@pytest.mark.parametrize(
    ("force", "generated_at", "expected_calls"),
    [
        (False, _stamp(NOW), 0),  # fresh, same local day, not forced -> skip both
        (True, _stamp(NOW), 1),  # forced -> refetch both despite being fresh
        (False, _stamp(NOW - timedelta(days=1)), 1),  # day rolled -> refetch both
    ],
    ids=["skip_fresh", "force", "day_rollover"],
)
def test_refresh_once_ttl_gating(
    monkeypatch: pytest.MonkeyPatch,
    force: bool,
    generated_at: str,
    expected_calls: int,
) -> None:
    # One parametrized test for the three freshness-gate paths that used to be
    # three near-identical copies: a fresh source is skipped, `force` overrides
    # the skip, and a local-day rollover (doc built yesterday) also overrides it.
    monkeypatch.setattr(settings, "weather_ttl_seconds", 3600)
    monkeypatch.setattr(settings, "calendar_ttl_seconds", 3600)
    _seed_cache(
        weather=_weather_block(
            temp_f=68, fetched_at=_stamp(NOW - timedelta(minutes=5)), ttl=3600
        ),
        calendar=_calendar_block(
            fetched_at=_stamp(NOW - timedelta(minutes=5)), ttl=3600
        ),
        generated_at=generated_at,
    )
    weather = Recorder(_weather_block(temp_f=72, fetched_at=_stamp(NOW)))
    calendar = Recorder(_calendar_block(fetched_at=_stamp(NOW)))
    _patch_sources(monkeypatch, weather=weather, calendar=calendar)

    asyncio.run(main._refresh_once(force=force, now=NOW))
    assert weather.calls == expected_calls
    assert calendar.calls == expected_calls


def test_refresh_once_weather_failure_keeps_last_good_but_calendar_updates(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Seed weather that is ALREADY past its TTL (2h old, 1h TTL) so it's due: the
    # fetch is attempted, fails, and falls back to the last-good DATA (flagged
    # stale). The calendar is stale too and refreshes independently.
    _seed_cache(
        weather=_weather_block(
            temp_f=70, fetched_at=_stamp(NOW - timedelta(hours=2)), ttl=3600
        ),
        calendar=_calendar_block(fetched_at=_stamp(NOW - timedelta(hours=2)), ttl=900),
    )

    def boom() -> WeatherBlock:
        raise RuntimeError("open-meteo down")

    _patch_sources(
        monkeypatch,
        weather=boom,
        calendar=Recorder(_calendar_block(fetched_at=_stamp(NOW))),
    )
    healthy = asyncio.run(main._refresh_once(now=NOW))

    assert healthy is False  # a source fell back to stale this tick
    doc = cache.read(main._CACHE_KEY)
    assert doc is not None
    assert doc["weather"]["ok"] is False  # flagged stale
    assert doc["weather"]["current"]["temp_f"] == 70  # last-good DATA preserved
    assert doc["calendar"]["ok"] is True  # calendar still refreshed independently


def test_refresh_once_cold_boot_weather_failure_raises(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # No prior cache + weather fetch fails -> nothing to fall back on; the tick
    # raises (the loop catches it; the route stays 503 — honest cold-boot state).
    def boom() -> WeatherBlock:
        raise RuntimeError("down")

    _patch_sources(
        monkeypatch,
        weather=boom,
        calendar=Recorder(_calendar_block(fetched_at=_stamp(NOW))),
    )
    with pytest.raises(RuntimeError):
        asyncio.run(main._refresh_once(now=NOW))


def test_refresh_once_does_not_hammer_failed_calendar_within_floor(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # No-hammer at the orchestration level: with weather fresh but a calendar that
    # failed 10s ago, the tick must NOT re-hit Proton (its retry_floor = the TTL),
    # even though the loop would be ticking fast during a parallel outage.
    monkeypatch.setattr(settings, "weather_ttl_seconds", 900)
    monkeypatch.setattr(settings, "calendar_ttl_seconds", 900)
    _seed_cache(
        weather=_weather_block(
            temp_f=70, fetched_at=_stamp(NOW), ttl=900
        ),  # fresh -> weather also skipped
        calendar=_calendar_block(
            fetched_at=_stamp(NOW - timedelta(hours=2)),
            ok=False,
            attempted_at=_stamp(NOW - timedelta(seconds=10)),  # just failed
            ttl=900,
        ),
    )
    weather = Recorder(_weather_block(temp_f=72, fetched_at=_stamp(NOW)))
    calendar = Recorder(_calendar_block(fetched_at=_stamp(NOW)))
    _patch_sources(monkeypatch, weather=weather, calendar=calendar)

    asyncio.run(main._refresh_once(now=NOW))
    assert calendar.calls == 0  # within retry_floor -> Proton not re-attempted


def test_refresh_lock_serializes_concurrent_refreshes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # The app's central concurrency guarantee: POST /refresh can't race a
    # scheduled tick into overlapping _refresh_once runs. Fire two forced
    # refreshes concurrently and assert _refresh_once never runs re-entrantly —
    # the shared `_refresh_lock` serializes them (peak concurrency stays 1).
    state = {"active": 0, "peak": 0}

    async def slow_once(force: bool = False, *, now: datetime | None = None) -> bool:
        state["active"] += 1
        state["peak"] = max(state["peak"], state["active"])
        await asyncio.sleep(0.02)  # hold the lock long enough for a racer to try
        state["active"] -= 1
        return True

    monkeypatch.setattr(main, "_refresh_once", slow_once)

    async def run_two() -> None:
        await asyncio.gather(main.refresh(), main.refresh())

    asyncio.run(run_two())
    assert state["peak"] == 1  # never overlapped -> the lock held
