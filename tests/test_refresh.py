"""Refresh-loop orchestration: TTL-gated cadence, per-source last-good
fallback, clock-honesty, and failure backoff. Source coroutines are faked, so
the suite makes no network call.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Generic, TypeVar
from zoneinfo import ZoneInfo

import pytest
from conftest import calendar_block, weather_block

from app import cache, main
from app.config import settings
from app.contract import CalendarBlock, SourceBlock, WeatherBlock

TZ = ZoneInfo("America/New_York")
NOW = datetime(2026, 7, 1, 9, 0, tzinfo=TZ)

T = TypeVar("T")


def _stamp(dt: datetime) -> str:
    return dt.isoformat(timespec="seconds")


class Recorder(Generic[T]):
    """Returns a fixed result and counts calls - a typed `Mock.call_count`."""

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
    """Replace the two source coroutines with callables that return the block
    (or raise); `calendar` receives `last_good`."""

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
    """Seed the cache with a prior doc. A loose dict, not a `DashboardDoc`: a
    cached doc may predate a field (e.g. `generated_at`)."""
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
    # The loop ticks fast in backoff; a failed source still waits out retry_floor.
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
    failed: SourceBlock = {
        "ok": False,
        "fetched_at": _stamp(NOW - timedelta(hours=5)),  # last success, ancient
        "attempted_at": _stamp(NOW - timedelta(seconds=5)),  # just tried, failed
    }
    assert main._is_due(failed, ttl=900, now=NOW, force=False, retry_floor=900) is False


def test_is_due_failed_source_without_attempted_at_falls_back_to_fetched_at() -> None:
    # A block cached before attempted_at existed.
    failed: SourceBlock = {
        "ok": False,
        "fetched_at": _stamp(NOW - timedelta(seconds=5)),
    }
    assert main._is_due(failed, ttl=900, now=NOW, force=False, retry_floor=30) is False


# ── _backoff_delay: retry sooner after a failure, capped at base ─────────────


def test_backoff_grows_then_caps_at_base() -> None:
    base = 900
    assert main._backoff_delay(1, base) == 30
    assert main._backoff_delay(2, base) == 60
    assert main._backoff_delay(3, base) == 120
    assert main._backoff_delay(4, base) == 240
    # Both sides of the cap (960 -> 900), where an off-by-one in
    # `<< (failures - 1)` would hide.
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
    # 2026-03-08 is only 23h long: from 00:30 EST midnight is 22.5h away, not
    # the 23.5h a naive wall-clock delta gives.
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
    # A Pi mid-boot: timesyncd's runtime dir exists, NTP hasn't synced.
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
        weather=Recorder(weather_block(temp_f=72, fetched_at=_stamp(NOW))),
        calendar=Recorder(calendar_block(fetched_at=_stamp(NOW))),
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
    monkeypatch.setattr(settings, "weather_ttl_seconds", 3600)
    monkeypatch.setattr(settings, "calendar_ttl_seconds", 3600)
    _seed_cache(
        weather=weather_block(
            temp_f=68, fetched_at=_stamp(NOW - timedelta(minutes=5)), ttl=3600
        ),
        calendar=calendar_block(
            fetched_at=_stamp(NOW - timedelta(minutes=5)), ttl=3600
        ),
        generated_at=generated_at,
    )
    weather = Recorder(weather_block(temp_f=72, fetched_at=_stamp(NOW)))
    calendar = Recorder(calendar_block(fetched_at=_stamp(NOW)))
    _patch_sources(monkeypatch, weather=weather, calendar=calendar)

    asyncio.run(main._refresh_once(force=force, now=NOW))
    assert weather.calls == expected_calls
    assert calendar.calls == expected_calls


def test_refresh_once_weather_failure_keeps_last_good_but_calendar_updates(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Both sources seeded past their TTL, so both are due.
    _seed_cache(
        weather=weather_block(
            temp_f=70, fetched_at=_stamp(NOW - timedelta(hours=2)), ttl=3600
        ),
        calendar=calendar_block(fetched_at=_stamp(NOW - timedelta(hours=2)), ttl=900),
    )

    def boom() -> WeatherBlock:
        raise RuntimeError("open-meteo down")

    _patch_sources(
        monkeypatch,
        weather=boom,
        calendar=Recorder(calendar_block(fetched_at=_stamp(NOW))),
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
    # Nothing to fall back on; the loop catches this and the route stays 503.
    def boom() -> WeatherBlock:
        raise RuntimeError("down")

    _patch_sources(
        monkeypatch,
        weather=boom,
        calendar=Recorder(calendar_block(fetched_at=_stamp(NOW))),
    )
    with pytest.raises(RuntimeError):
        asyncio.run(main._refresh_once(now=NOW))


def test_refresh_once_does_not_hammer_failed_calendar_within_floor(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Calendar's retry_floor is its TTL, so a fast-ticking loop mustn't re-hit
    # Proton.
    monkeypatch.setattr(settings, "weather_ttl_seconds", 900)
    monkeypatch.setattr(settings, "calendar_ttl_seconds", 900)
    _seed_cache(
        weather=weather_block(
            temp_f=70, fetched_at=_stamp(NOW), ttl=900
        ),  # fresh -> weather also skipped
        calendar=calendar_block(
            fetched_at=_stamp(NOW - timedelta(hours=2)),
            ok=False,
            attempted_at=_stamp(NOW - timedelta(seconds=10)),  # just failed
            ttl=900,
        ),
    )
    weather = Recorder(weather_block(temp_f=72, fetched_at=_stamp(NOW)))
    calendar = Recorder(calendar_block(fetched_at=_stamp(NOW)))
    _patch_sources(monkeypatch, weather=weather, calendar=calendar)

    asyncio.run(main._refresh_once(now=NOW))
    assert calendar.calls == 0  # within retry_floor -> Proton not re-attempted


def test_refresh_lock_serializes_concurrent_refreshes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # POST /refresh must not race a scheduled tick into overlapping runs.
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


# ── _refresh_loop: the composition of tick → base/backoff → midnight clamp ────
# The pure pieces are pinned above; these test the wiring, with `_refresh_once`
# and `asyncio.sleep` faked so the requested delays are observable.


def _run_loop(
    monkeypatch: pytest.MonkeyPatch,
    outcomes: list[bool | Exception],
    *,
    now: datetime = NOW,
    weather_ttl: int = 900,
    calendar_ttl: int = 1800,
) -> list[float]:
    """Run `_refresh_loop` for `len(outcomes)` ticks (each a healthy flag or an
    exception to raise) and return the requested sleep delays.

    The clock is frozen: a real one near local midnight would let the midnight
    clamp swallow the cadence (a once-a-day flake). The final sleep cancels the
    otherwise-unkillable loop."""
    monkeypatch.setattr(settings, "weather_ttl_seconds", weather_ttl)
    monkeypatch.setattr(settings, "calendar_ttl_seconds", calendar_ttl)

    class Frozen:
        """The one classmethod the loop body calls, pinned to `now`."""

        @staticmethod
        def now(tz: ZoneInfo | None = None) -> datetime:
            return now if tz is None else now.astimezone(tz)

    monkeypatch.setattr(main, "datetime", Frozen)

    results = iter(outcomes)

    async def fake_once(force: bool = False, *, now: datetime | None = None) -> bool:
        outcome = next(results)
        if isinstance(outcome, Exception):
            raise outcome
        return outcome

    monkeypatch.setattr(main, "_refresh_once", fake_once)

    delays: list[float] = []

    async def fake_sleep(delay: float) -> None:
        delays.append(delay)
        if len(delays) >= len(outcomes):
            raise asyncio.CancelledError

    monkeypatch.setattr(asyncio, "sleep", fake_sleep)

    with pytest.raises(asyncio.CancelledError):
        asyncio.run(main._refresh_loop())
    return delays


def test_refresh_loop_healthy_tick_sleeps_the_shortest_ttl(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Base cadence = min(weather, calendar) TTL; healthy ticks never back off.
    delays = _run_loop(monkeypatch, [True, True], weather_ttl=900, calendar_ttl=1800)
    assert delays == [900.0, 900.0]


def test_refresh_loop_backs_off_on_failure_and_resets_on_recovery(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # The trailing 30 proves the failure counter reset on recovery (else 240).
    delays = _run_loop(monkeypatch, [False, False, False, True, False])
    assert delays == [30.0, 60.0, 120.0, 900.0, 30.0]


def test_refresh_loop_survives_a_raising_tick_and_backs_off(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    delays = _run_loop(monkeypatch, [RuntimeError("tick exploded"), True])
    assert delays == [30.0, 900.0]


def test_refresh_loop_clamps_sleep_to_just_past_local_midnight(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # So the day-rollover refresh fires at the boundary, not a full interval late.
    near_midnight = datetime(2026, 7, 1, 23, 59, 0, tzinfo=TZ)
    delays = _run_loop(monkeypatch, [True], now=near_midnight)
    assert delays == [61.0]
