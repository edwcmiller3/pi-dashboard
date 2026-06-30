"""Phase 6 — refresh-loop orchestration: TTL-gated cadence, per-source last-good
fallback, clock-honesty, and failure backoff.

The pure helpers (`_is_due`, `_backoff_delay`, `_clock_synced`) are tested
directly; `_refresh_once` is exercised with the source coroutines and the cache
monkeypatched so the suite makes no network call and writes only to a tmp dir.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import pytest

from app import cache, main
from app.config import settings
from app.contract import SourceBlock

TZ = ZoneInfo("America/New_York")
NOW = datetime(2026, 7, 1, 9, 0, tzinfo=TZ)


def _stamp(dt: datetime) -> str:
    return dt.isoformat(timespec="seconds")


# ── _is_due: TTL-gated cadence ───────────────────────────────────────────────


def test_is_due_when_no_prior_block() -> None:
    assert main._is_due(None, ttl=900, now=NOW, force=False, retry_floor=30) is True


def test_is_due_when_forced_even_if_fresh() -> None:
    fresh: SourceBlock = {"ok": True, "fetched_at": _stamp(NOW)}
    assert main._is_due(fresh, ttl=900, now=NOW, force=True, retry_floor=30) is True


def test_not_due_when_fresh_within_ttl() -> None:
    fresh: SourceBlock = {
        "ok": True,
        "fetched_at": _stamp(NOW - timedelta(seconds=300)),
    }
    assert main._is_due(fresh, ttl=900, now=NOW, force=False, retry_floor=30) is False


def test_due_when_aged_beyond_ttl() -> None:
    old: SourceBlock = {"ok": True, "fetched_at": _stamp(NOW - timedelta(seconds=1200))}
    assert main._is_due(old, ttl=900, now=NOW, force=False, retry_floor=30) is True


def test_due_when_fetched_at_missing_or_unparseable() -> None:
    miss: SourceBlock = {"ok": True, "fetched_at": None}
    junk: SourceBlock = {"ok": True, "fetched_at": "garbage"}
    assert main._is_due(miss, 900, NOW, False, retry_floor=30) is True
    assert main._is_due(junk, 900, NOW, False, retry_floor=30) is True


# ── _is_due: failed-source retry is rate-limited (no-hammer) ──────────────────


def test_failed_source_not_due_within_retry_floor() -> None:
    # The no-hammer guard: a source that failed 10s ago must NOT be retried while
    # the loop is in fast backoff — only once retry_floor has elapsed.
    failed: SourceBlock = {
        "ok": False,
        "fetched_at": None,
        "attempted_at": _stamp(NOW - timedelta(seconds=10)),
    }
    assert main._is_due(failed, ttl=900, now=NOW, force=False, retry_floor=30) is False


def test_failed_source_due_after_retry_floor() -> None:
    failed: SourceBlock = {
        "ok": False,
        "fetched_at": None,
        "attempted_at": _stamp(NOW - timedelta(seconds=40)),
    }
    assert main._is_due(failed, ttl=900, now=NOW, force=False, retry_floor=30) is True


def test_failed_source_rate_limit_uses_last_attempt_not_last_success() -> None:
    # A block whose last SUCCESS is ancient but was just RE-attempted must stay
    # rate-limited: attempted_at (not the stale fetched_at) governs the retry.
    failed: SourceBlock = {
        "ok": False,
        "fetched_at": _stamp(NOW - timedelta(hours=5)),  # last success, ancient
        "attempted_at": _stamp(NOW - timedelta(seconds=5)),  # just tried, failed
    }
    assert main._is_due(failed, ttl=900, now=NOW, force=False, retry_floor=900) is False


def test_failed_source_without_attempted_at_falls_back_to_fetched_at() -> None:
    # A failed block written before attempted_at existed rate-limits off fetched_at.
    failed: SourceBlock = {
        "ok": False,
        "fetched_at": _stamp(NOW - timedelta(seconds=5)),
    }
    assert main._is_due(failed, ttl=900, now=NOW, force=False, retry_floor=30) is False


# ── _backoff_delay: retry sooner after a failure, capped at base ─────────────


def test_backoff_grows_then_caps_at_base() -> None:
    base = 900
    # 30, 60, 120, 240, 480, then capped at base (900)
    assert main._backoff_delay(1, base) == 30
    assert main._backoff_delay(2, base) == 60
    assert main._backoff_delay(3, base) == 120
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
    monkeypatch.setattr(main, "_TIMESYNC_MARKER", tmp_path / "synchronized")
    assert main._clock_synced() is False


def test_clock_synced_true_when_no_timesync_runtime(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    # Non-systemd host (the dev Mac): can't determine -> assume synced, don't nag.
    monkeypatch.setattr(main, "_TIMESYNC_MARKER", tmp_path / "absent" / "synchronized")
    assert main._clock_synced() is True


# ── _refresh_once: assembly, last-good, TTL gating, force ─────────────────────


def _patch_sources(
    monkeypatch: pytest.MonkeyPatch,
    *,
    weather: Callable[[], dict[str, Any]],
    calendar: Callable[..., dict[str, Any]],
) -> None:
    """Replace the two source coroutines. `weather`/`calendar` are callables
    returning the block (or raising) — invoked with no args / the kwargs main
    passes."""

    async def fake_weather() -> dict[str, Any]:
        return weather()

    async def fake_calendar(now: Any = None, last_good: Any = None) -> dict[str, Any]:
        return calendar(last_good)

    monkeypatch.setattr(main, "get_weather", fake_weather)
    monkeypatch.setattr(main, "get_calendar", fake_calendar)


def _good_weather() -> dict[str, Any]:
    return {
        "ok": True,
        "fetched_at": _stamp(NOW),
        "current": {"temp_f": 72},
        "forecast": [],
    }


def _good_calendar(last_good: Any = None) -> dict[str, Any]:
    return {"ok": True, "fetched_at": _stamp(NOW), "events": []}


def test_refresh_once_assembles_doc_with_ttls_and_clock(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(settings, "cache_dir", str(tmp_path))
    monkeypatch.setattr(settings, "weather_ttl_seconds", 3600)
    monkeypatch.setattr(settings, "calendar_ttl_seconds", 900)
    monkeypatch.setattr(main, "_clock_synced", lambda: True)
    _patch_sources(monkeypatch, weather=_good_weather, calendar=_good_calendar)

    healthy = asyncio.run(main._refresh_once(now=NOW))
    assert healthy is True
    doc = cache.read(main._CACHE_KEY)
    assert doc is not None
    assert doc["clock_synced"] is True
    assert "generated_at" in doc
    assert doc["weather"]["ttl"] == 3600  # stamped per-source for the contract
    assert doc["calendar"]["ttl"] == 900
    assert doc["weather"]["current"]["temp_f"] == 72


def test_refresh_once_weather_failure_keeps_last_good_but_calendar_updates(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(settings, "cache_dir", str(tmp_path))
    # Seed a last-good doc with fresh-but-soon-to-be-stale weather.
    cache.write(
        main._CACHE_KEY,
        {
            "weather": {
                "ok": True,
                "fetched_at": _stamp(NOW - timedelta(hours=2)),
                "current": {"temp_f": 70},
                "forecast": [],
                "ttl": 3600,
            },
            "calendar": {
                "ok": True,
                "fetched_at": _stamp(NOW - timedelta(hours=2)),
                "events": [],
                "ttl": 900,
            },
        },
    )

    def boom() -> dict[str, Any]:
        raise RuntimeError("open-meteo down")

    _patch_sources(monkeypatch, weather=boom, calendar=_good_calendar)
    healthy = asyncio.run(main._refresh_once(now=NOW))

    assert healthy is False  # a source fell back to stale this tick
    doc = cache.read(main._CACHE_KEY)
    assert doc is not None
    assert doc["weather"]["ok"] is False  # flagged stale
    assert doc["weather"]["current"]["temp_f"] == 70  # last-good DATA preserved
    assert doc["calendar"]["ok"] is True  # calendar still refreshed independently


def test_refresh_once_cold_boot_weather_failure_raises(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    # No prior cache + weather fetch fails -> nothing to fall back on; the tick
    # raises (the loop catches it; the route stays 503 — honest cold-boot state).
    monkeypatch.setattr(settings, "cache_dir", str(tmp_path))

    def boom() -> dict[str, Any]:
        raise RuntimeError("down")

    _patch_sources(monkeypatch, weather=boom, calendar=_good_calendar)
    with pytest.raises(RuntimeError):
        asyncio.run(main._refresh_once(now=NOW))


def test_refresh_once_skips_fresh_source_within_ttl(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(settings, "cache_dir", str(tmp_path))
    monkeypatch.setattr(settings, "weather_ttl_seconds", 3600)
    monkeypatch.setattr(settings, "calendar_ttl_seconds", 900)
    # Prior weather is 5 min old (< 1h ttl) -> must NOT be refetched.
    cache.write(
        main._CACHE_KEY,
        {
            "weather": {
                "ok": True,
                "fetched_at": _stamp(NOW - timedelta(minutes=5)),
                "current": {"temp_f": 68},
                "forecast": [],
                "ttl": 3600,
            },
            "calendar": {
                "ok": True,
                "fetched_at": _stamp(NOW - timedelta(minutes=5)),
                "events": [],
                "ttl": 900,
            },
        },
    )
    calls = {"weather": 0}

    def counted_weather() -> dict[str, Any]:
        calls["weather"] += 1
        return _good_weather()

    _patch_sources(monkeypatch, weather=counted_weather, calendar=_good_calendar)
    asyncio.run(main._refresh_once(now=NOW))
    assert calls["weather"] == 0  # skipped — still fresh within its TTL
    skipped = cache.read(main._CACHE_KEY)
    assert skipped is not None
    assert skipped["weather"]["current"]["temp_f"] == 68


def test_refresh_once_force_refetches_even_when_fresh(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(settings, "cache_dir", str(tmp_path))
    monkeypatch.setattr(settings, "weather_ttl_seconds", 3600)
    cache.write(
        main._CACHE_KEY,
        {
            "weather": {
                "ok": True,
                "fetched_at": _stamp(NOW),
                "current": {"temp_f": 68},
                "forecast": [],
                "ttl": 3600,
            },
            "calendar": {
                "ok": True,
                "fetched_at": _stamp(NOW),
                "events": [],
                "ttl": 900,
            },
        },
    )
    calls = {"weather": 0}

    def counted_weather() -> dict[str, Any]:
        calls["weather"] += 1
        return _good_weather()

    _patch_sources(monkeypatch, weather=counted_weather, calendar=_good_calendar)
    asyncio.run(main._refresh_once(force=True, now=NOW))
    assert calls["weather"] == 1  # forced refetch despite being fresh


def test_refresh_once_does_not_hammer_failed_calendar_within_floor(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    # No-hammer at the orchestration level: with weather fresh but a calendar that
    # failed 10s ago, the tick must NOT re-hit Proton (its retry_floor = the TTL),
    # even though the loop would be ticking fast during a parallel outage.
    monkeypatch.setattr(settings, "cache_dir", str(tmp_path))
    monkeypatch.setattr(settings, "weather_ttl_seconds", 900)
    monkeypatch.setattr(settings, "calendar_ttl_seconds", 900)
    cache.write(
        main._CACHE_KEY,
        {
            "weather": {
                "ok": True,
                "fetched_at": _stamp(NOW),  # fresh -> weather also skipped
                "current": {"temp_f": 70},
                "forecast": [],
                "ttl": 900,
            },
            "calendar": {
                "ok": False,
                "fetched_at": _stamp(NOW - timedelta(hours=2)),
                "attempted_at": _stamp(NOW - timedelta(seconds=10)),  # just failed
                "events": [],
                "ttl": 900,
            },
        },
    )
    calls = {"calendar": 0}

    def counted_calendar(last_good: Any = None) -> dict[str, Any]:
        calls["calendar"] += 1
        return _good_calendar()

    _patch_sources(monkeypatch, weather=_good_weather, calendar=counted_calendar)
    asyncio.run(main._refresh_once(now=NOW))
    assert calls["calendar"] == 0  # within retry_floor -> Proton not re-attempted


def test_refresh_once_forces_refresh_on_day_rollover(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    # At local midnight the agenda window must roll even though every source is
    # well within its TTL: a doc generated YESTERDAY forces a full refetch this
    # tick, so today's column rolls and a holiday/event entering the window shows.
    monkeypatch.setattr(settings, "cache_dir", str(tmp_path))
    monkeypatch.setattr(settings, "weather_ttl_seconds", 3600)
    monkeypatch.setattr(settings, "calendar_ttl_seconds", 3600)
    cache.write(
        main._CACHE_KEY,
        {
            "generated_at": _stamp(NOW - timedelta(days=1)),  # built yesterday
            "weather": {
                "ok": True,
                "fetched_at": _stamp(NOW - timedelta(minutes=5)),  # fresh in TTL
                "current": {"temp_f": 68},
                "forecast": [],
                "ttl": 3600,
            },
            "calendar": {
                "ok": True,
                "fetched_at": _stamp(NOW - timedelta(minutes=5)),  # fresh in TTL
                "events": [],
                "ttl": 3600,
            },
        },
    )
    calls = {"weather": 0, "calendar": 0}

    def counted_weather() -> dict[str, Any]:
        calls["weather"] += 1
        return _good_weather()

    def counted_calendar(last_good: Any = None) -> dict[str, Any]:
        calls["calendar"] += 1
        return _good_calendar()

    _patch_sources(monkeypatch, weather=counted_weather, calendar=counted_calendar)
    asyncio.run(main._refresh_once(now=NOW))
    # both refetched despite being fresh within TTL — the day rolled
    assert calls == {"weather": 1, "calendar": 1}
