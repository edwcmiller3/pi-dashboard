"""Phase 5 — calendar adapter tests.

The heart is `normalize_events`, the pure transform from raw ICS text to the
contract's personal agenda-items (recurrence expansion + EXDATE + the
DATE-vs-DATETIME split), tested against a synthetic fixture (no real PII). The
fetch/merge wrapper `get_calendar` is exercised with the network monkeypatched
out, asserting the Proton-only `ok` semantics and the holidays-always-merge rule.
"""

from __future__ import annotations

import asyncio
from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

from app.config import settings
from app.sources import calendar

TZ = ZoneInfo("America/New_York")
# Deterministic reference: Wed 2026-07-01 09:00 EDT. Window = [07-01, 07-06).
NOW = datetime(2026, 7, 1, 9, 0, tzinfo=TZ)

# Synthetic Proton-shaped feed: an all-day event, a timed event, a DAILY
# recurrence with one EXDATE-excluded occurrence, and one event OUTSIDE the
# window. VTIMEZONE rides along like the real feed (0.D1).
ICS = """\
BEGIN:VCALENDAR
VERSION:2.0
PRODID:-//Proton//Calendar//EN
X-WR-TIMEZONE:America/New_York
BEGIN:VTIMEZONE
TZID:America/New_York
BEGIN:DAYLIGHT
TZOFFSETFROM:-0500
TZOFFSETTO:-0400
TZNAME:EDT
DTSTART:20070311T020000
RRULE:FREQ=YEARLY;BYMONTH=3;BYDAY=2SU
END:DAYLIGHT
BEGIN:STANDARD
TZOFFSETFROM:-0400
TZOFFSETTO:-0500
TZNAME:EST
DTSTART:20071104T020000
RRULE:FREQ=YEARLY;BYMONTH=11;BYDAY=1SU
END:STANDARD
END:VTIMEZONE
BEGIN:VEVENT
UID:allday@test
DTSTART;VALUE=DATE:20260704
SUMMARY:Cabin trip
END:VEVENT
BEGIN:VEVENT
UID:timed@test
DTSTART;TZID=America/New_York:20260701T083000
SUMMARY:Team standup
END:VEVENT
BEGIN:VEVENT
UID:daily@test
DTSTART;TZID=America/New_York:20260701T120000
RRULE:FREQ=DAILY
EXDATE;TZID=America/New_York:20260703T120000
SUMMARY:Lunch walk
END:VEVENT
BEGIN:VEVENT
UID:outside@test
DTSTART;TZID=America/New_York:20260720T100000
SUMMARY:Way out there
END:VEVENT
END:VCALENDAR
"""


# A WEEKLY 10:00-local event straddling the 2026-11-01 DST end (EDT->EST). 0.D1
# proved `recurring_ical_events` preserves local wall-clock across DST; this
# asserts that survives `normalize_events` — the wall-clock stays 10:00 while the
# emitted offset flips -04:00 -> -05:00. Same VTIMEZONE as ICS.
DST_ICS = """\
BEGIN:VCALENDAR
VERSION:2.0
PRODID:-//Proton//Calendar//EN
BEGIN:VTIMEZONE
TZID:America/New_York
BEGIN:DAYLIGHT
TZOFFSETFROM:-0500
TZOFFSETTO:-0400
TZNAME:EDT
DTSTART:20070311T020000
RRULE:FREQ=YEARLY;BYMONTH=3;BYDAY=2SU
END:DAYLIGHT
BEGIN:STANDARD
TZOFFSETFROM:-0400
TZOFFSETTO:-0500
TZNAME:EST
DTSTART:20071104T020000
RRULE:FREQ=YEARLY;BYMONTH=11;BYDAY=1SU
END:STANDARD
END:VTIMEZONE
BEGIN:VEVENT
UID:dstweekly@test
DTSTART;TZID=America/New_York:20261028T100000
RRULE:FREQ=WEEKLY
SUMMARY:Weekly sync
END:VEVENT
END:VCALENDAR
"""


# A multi-day all-day event that BEGAN before the window but overlaps it (a trip
# in progress), alongside an in-window event. `between` returns both; only the
# in-window one should survive normalization. No VTIMEZONE needed (all-day only).
MULTIDAY_ICS = """\
BEGIN:VCALENDAR
VERSION:2.0
PRODID:-//Proton//Calendar//EN
BEGIN:VEVENT
UID:vacation@test
DTSTART;VALUE=DATE:20260628
DTEND;VALUE=DATE:20260703
SUMMARY:Vacation
END:VEVENT
BEGIN:VEVENT
UID:lunch@test
DTSTART;VALUE=DATE:20260702
SUMMARY:Mid-week lunch
END:VEVENT
END:VCALENDAR
"""


def _personal(ics: str = ICS) -> list[dict[str, Any]]:
    start, end = calendar._window(NOW)
    return calendar.normalize_events(ics, start, end, TZ)


# ── _window ──────────────────────────────────────────────────────────────────


def test_window_is_today_plus_four_future_days_tz_aware() -> None:
    start, end = calendar._window(NOW)
    assert start == datetime(2026, 7, 1, 0, 0, tzinfo=TZ)  # start-of-today
    assert end == datetime(2026, 7, 6, 0, 0, tzinfo=TZ)  # exclusive, +5 days
    assert start.tzinfo is not None and end.tzinfo is not None


# ── normalize_events: DATE vs DATETIME split ──────────────────────────────────


def test_all_day_event_is_date_only_and_flagged() -> None:
    cabin = next(e for e in _personal() if e["title"] == "Cabin trip")
    assert cabin["start"] == "2026-07-04"  # date-only, no "T"
    assert cabin["all_day"] is True
    assert cabin["kind"] == "personal"


def test_timed_event_is_iso_with_offset() -> None:
    standup = next(e for e in _personal() if e["title"] == "Team standup")
    assert standup["start"] == "2026-07-01T08:30:00-04:00"  # EDT offset attached
    assert standup["all_day"] is False


# ── normalize_events: recurrence + EXDATE + windowing ─────────────────────────


def test_recurrence_expands_within_window_and_honors_exdate() -> None:
    walks = sorted(e["start"] for e in _personal() if e["title"] == "Lunch walk")
    # DAILY from 07-01; 07-03 EXDATE-excluded; 07-06 == exclusive end -> dropped.
    assert walks == [
        "2026-07-01T12:00:00-04:00",
        "2026-07-02T12:00:00-04:00",
        "2026-07-04T12:00:00-04:00",
        "2026-07-05T12:00:00-04:00",
    ]


def test_recurrence_preserves_local_walltime_across_dst() -> None:
    # Window straddles the 2026-11-01 EDT->EST transition. The weekly 10:00-local
    # event must keep wall-clock 10:00 while the emitted offset flips -04:00 (EDT,
    # 10-28) -> -05:00 (EST, 11-04 onward) — the contract's offset-bearing start.
    start = datetime(2026, 10, 28, 0, 0, tzinfo=TZ)
    end = datetime(2026, 11, 12, 0, 0, tzinfo=TZ)
    syncs = sorted(
        e["start"]
        for e in calendar.normalize_events(DST_ICS, start, end, TZ)
        if e["title"] == "Weekly sync"
    )
    assert syncs == [
        "2026-10-28T10:00:00-04:00",  # EDT, before DST end
        "2026-11-04T10:00:00-05:00",  # EST, after DST end (wall-clock unchanged)
        "2026-11-11T10:00:00-05:00",  # EST
    ]
    # every occurrence reads 10:00 local regardless of which side of DST it's on
    assert all(s[11:16] == "10:00" for s in syncs)


def test_event_outside_window_is_excluded() -> None:
    assert all(e["title"] != "Way out there" for e in _personal())


def test_multiday_event_starting_before_window_is_filtered() -> None:
    # `between` returns events OVERLAPPING the window, incl. a trip that began
    # before it — its out-of-window start would bucket into a day the agenda
    # never renders, so it's filtered (matching the holidays date filter).
    items = calendar.normalize_events(MULTIDAY_ICS, *calendar._window(NOW), TZ)
    titles = {e["title"] for e in items}
    assert "Vacation" not in titles  # started 06-28, before the 07-01 window
    assert "Mid-week lunch" in titles  # 07-02, in window — filter isn't over-broad
    assert all(e["start"][:10] >= "2026-07-01" for e in items)


def test_total_personal_event_count() -> None:
    # 1 all-day + 1 timed + 4 recurrence occurrences = 6.
    assert len(_personal()) == 6


def test_missing_summary_becomes_empty_title() -> None:
    ics = ICS.replace("SUMMARY:Team standup\n", "")
    standup = next(
        e
        for e in calendar.normalize_events(ics, *calendar._window(NOW), TZ)
        if e["start"] == "2026-07-01T08:30:00-04:00"
    )
    assert standup["title"] == ""


# ── _merge: ordering + shape ──────────────────────────────────────────────────


def test_merge_sorts_all_day_before_same_day_timed() -> None:
    personal = [
        {
            "start": "2026-07-04T09:00:00-04:00",
            "all_day": False,
            "title": "Brunch",
            "kind": "personal",
        },
    ]
    holiday = [
        {
            "start": "2026-07-04",
            "all_day": True,
            "title": "Independence Day",
            "kind": "holiday",
        },
    ]
    block = calendar._merge(True, "2026-07-01T09:00:00-04:00", personal, holiday)
    # date-only all-day holiday leads the day; timed personal follows.
    assert [e["title"] for e in block["events"]] == ["Independence Day", "Brunch"]
    assert block["ok"] is True
    assert block["fetched_at"] == "2026-07-01T09:00:00-04:00"


# ── get_calendar: fetch/merge wrapper (network monkeypatched out) ──────────────


def test_get_calendar_ok_merges_personal_and_holidays(monkeypatch: Any) -> None:
    monkeypatch.setattr(settings, "proton_ics_url", "https://example/secret.ics")
    monkeypatch.setattr(
        calendar, "_fetch_personal", lambda url, start, end, tz: _personal()
    )
    block = asyncio.run(calendar.get_calendar(NOW))
    assert block["ok"] is True
    assert block["fetched_at"] is not None and block["fetched_at"].endswith("-04:00")
    titles = {e["title"] for e in block["events"]}
    assert "Team standup" in titles  # personal merged
    assert "Independence Day" in titles  # offline federal holiday merged (07-04)
    # flat, sorted, no day grouping (frontend groups)
    starts = [e["start"] for e in block["events"]]
    assert starts == sorted(starts, key=lambda s: (s,))


def test_get_calendar_proton_failure_still_shows_holidays(monkeypatch: Any) -> None:
    monkeypatch.setattr(settings, "proton_ics_url", "https://example/secret.ics")

    def boom(url: str, start: Any, end: Any, tz: Any) -> Any:
        raise RuntimeError("network down")

    monkeypatch.setattr(calendar, "_fetch_personal", boom)
    block = asyncio.run(calendar.get_calendar(NOW))
    assert block["ok"] is False  # ok tracks the Proton fetch only
    assert block["fetched_at"] is None
    # holidays still merge in regardless of the Proton outage
    assert any(e["title"] == "Independence Day" for e in block["events"])
    assert all(e["kind"] != "personal" for e in block["events"])


def test_get_calendar_no_url_is_holidays_only(monkeypatch: Any) -> None:
    monkeypatch.setattr(settings, "proton_ics_url", "")
    block = asyncio.run(calendar.get_calendar(NOW))
    assert block["ok"] is False
    assert block["fetched_at"] is None
    assert any(e["title"] == "Independence Day" for e in block["events"])


def test_get_calendar_proton_failure_keeps_last_good_personal(monkeypatch: Any) -> None:
    # Phase 6 per-source last-good: a transient Proton blip must NOT wipe the
    # user's personal events from the agenda. With a last-good doc in hand, the
    # in-window personal events are kept (ok=False) and holidays still merge.
    monkeypatch.setattr(settings, "proton_ics_url", "https://example/secret.ics")

    def boom(url: str, start: Any, end: Any, tz: Any) -> Any:
        raise RuntimeError("network down")

    monkeypatch.setattr(calendar, "_fetch_personal", boom)
    last_good = {
        "ok": True,
        "fetched_at": "2026-07-01T08:00:00-04:00",
        "events": [
            {
                "start": "2026-07-02T08:30:00-04:00",
                "all_day": False,
                "title": "Team standup",
                "kind": "personal",
            },
            # A holiday in last-good must NOT be carried as personal (holidays are
            # recomputed fresh every tick); only kind=="personal" survives.
            {
                "start": "2026-07-04",
                "all_day": True,
                "title": "Independence Day",
                "kind": "holiday",
            },
        ],
    }
    block = asyncio.run(calendar.get_calendar(NOW, last_good=last_good))
    assert block["ok"] is False  # still flagged stale (Proton fetch failed)
    titles = [e["title"] for e in block["events"]]
    assert "Team standup" in titles  # last-good personal event preserved
    assert (
        titles.count("Independence Day") == 1
    )  # holiday merged once (fresh), not doubled


def test_get_calendar_last_good_personal_outside_window_is_dropped(
    monkeypatch: Any,
) -> None:
    # As the window slides during a prolonged outage, last-good personal events
    # that fall out of [today, today+5) must drop (else they bucket into a day
    # the agenda never renders) — matching the live-fetch window filter.
    monkeypatch.setattr(settings, "proton_ics_url", "https://example/secret.ics")
    monkeypatch.setattr(
        calendar,
        "_fetch_personal",
        lambda url, s, e, tz: (_ for _ in ()).throw(RuntimeError("down")),
    )
    last_good = {
        "ok": True,
        "fetched_at": None,
        "events": [
            {
                "start": "2026-06-20T08:30:00-04:00",  # well before the 07-01 window
                "all_day": False,
                "title": "Old meeting",
                "kind": "personal",
            },
        ],
    }
    block = asyncio.run(calendar.get_calendar(NOW, last_good=last_good))
    assert all(e["title"] != "Old meeting" for e in block["events"])


def test_get_calendar_failure_does_not_leak_url(monkeypatch: Any, caplog: Any) -> None:
    secret = "https://calendar.proton.me/SECRET-TOKEN-xyz?PassphraseKey=DECRYPTKEY"
    monkeypatch.setattr(settings, "proton_ics_url", secret)

    def boom(url: str, start: Any, end: Any, tz: Any) -> Any:
        raise requests_like_error(url)

    monkeypatch.setattr(calendar, "_fetch_personal", boom)
    import logging

    with caplog.at_level(logging.WARNING):
        asyncio.run(calendar.get_calendar(NOW))
    # the secret URL (and its key) must never reach the logs
    assert "SECRET-TOKEN" not in caplog.text
    assert "PassphraseKey" not in caplog.text
    assert "DECRYPTKEY" not in caplog.text


def requests_like_error(url: str) -> Exception:
    # Mimic a requests exception whose message embeds the full URL+key.
    return RuntimeError(f"HTTPSConnectionPool: failed to GET {url}")
