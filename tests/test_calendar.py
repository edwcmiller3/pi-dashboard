"""Phase 5 — calendar adapter tests.

The heart is `normalize_events`, the pure transform from raw ICS text to the
contract's personal agenda-items (recurrence expansion + EXDATE + the
DATE-vs-DATETIME split), tested against a synthetic fixture (no real PII). The
fetch/merge wrapper `get_calendar` is exercised with the network monkeypatched
out, asserting the Proton-only `ok` semantics and the holidays-always-merge rule.
"""

from __future__ import annotations

import asyncio
import logging
import re
from collections.abc import Callable
from datetime import datetime
from typing import NoReturn
from zoneinfo import ZoneInfo

import pytest

from app.config import settings
from app.contract import AgendaItem, CalendarBlock, Kind
from app.sources import calendar

TZ = ZoneInfo("America/New_York")
# Deterministic reference: Wed 2026-07-01 09:00 EDT. Window = [07-01, 07-06).
NOW = datetime(2026, 7, 1, 9, 0, tzinfo=TZ)

# The monkeypatch stubs below mirror the real `calendar._fetch_personal`
# signature exactly — `(str, datetime, datetime, ZoneInfo) -> list[AgendaItem]`,
# raising ones `-> NoReturn` — rather than `*args: Any`, so a stub that drifts
# from the seam fails the type-check instead of silently dropping checking there.

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
DTEND;TZID=America/New_York:20260701T090000
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


def _personal(ics: str = ICS) -> list[AgendaItem]:
    start, end = calendar._window(NOW)
    return calendar.normalize_events(ics, start, end, TZ)


def _patch_fetch_returns(
    monkeypatch: pytest.MonkeyPatch, items: list[AgendaItem]
) -> None:
    """Replace `_fetch_personal` with a typed stub returning `items`."""

    def stub(
        url: str, start: datetime, end: datetime, tz: ZoneInfo
    ) -> list[AgendaItem]:
        return items

    monkeypatch.setattr(calendar, "_fetch_personal", stub)


def _patch_fetch_raises(
    monkeypatch: pytest.MonkeyPatch,
    make_error: Callable[[str], Exception] | None = None,
) -> None:
    """Replace `_fetch_personal` with a typed stub that raises — the single
    failure-injector for every Proton-outage test (was 3 copied `boom` defs plus
    a throw-in-a-generator lambda). `make_error` can build the exception from the
    URL (used by the secret-leak test to embed the credential in the message)."""

    def boom(url: str, start: datetime, end: datetime, tz: ZoneInfo) -> NoReturn:
        raise make_error(url) if make_error else RuntimeError("network down")

    monkeypatch.setattr(calendar, "_fetch_personal", boom)


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


# ── normalize_events: end (half-open interval [start, end)) ───────────────────


def test_timed_event_carries_end_as_offset_instant() -> None:
    # `end` is the exclusive end instant, same ISO-with-offset form as `start`.
    standup = next(e for e in _personal() if e["title"] == "Team standup")
    assert standup["end"] == "2026-07-01T09:00:00-04:00"  # 08:30 + 30 min, EDT


def test_timed_event_without_dtend_has_end_equal_to_start() -> None:
    # A timed VEVENT with no DTEND is zero-duration: the lib synthesizes
    # DTEND == DTSTART, so the contract's `end` equals `start` (empty interval).
    # Selected by TITLE (the stable identifier) and asserted for every "Lunch
    # walk" occurrence, so a recurrence regression surfaces as a clear failure.
    walks = [e for e in _personal() if e["title"] == "Lunch walk"]
    assert walks  # sanity: the recurrence produced occurrences
    assert all(e["end"] == e["start"] for e in walks)


def test_all_day_single_day_end_is_exclusive_next_day() -> None:
    # ICS DTEND is exclusive; a single-day all-day event (07-04, no DTEND) gets a
    # synthesized DTEND of 07-05, so the contract `end` is the day AFTER the one
    # day it covers — date-only, symmetric with the date-only `start`.
    cabin = next(e for e in _personal() if e["title"] == "Cabin trip")
    assert cabin["start"] == "2026-07-04"
    assert cabin["end"] == "2026-07-05"  # exclusive; covers the dates [07-04, 07-05)


def test_multiday_all_day_end_is_exclusive_upper_bound() -> None:
    # A multi-day all-day event STARTING in-window keeps ICS's exclusive DTEND,
    # so the covered dates are [start, end) — 07-02, 07-03, 07-04 here (not 07-05).
    ics = """\
BEGIN:VCALENDAR
VERSION:2.0
PRODID:-//Proton//Calendar//EN
BEGIN:VEVENT
UID:conf@test
DTSTART;VALUE=DATE:20260702
DTEND;VALUE=DATE:20260705
SUMMARY:Conference
END:VEVENT
END:VCALENDAR
"""
    conf = next(
        e
        for e in calendar.normalize_events(ics, *calendar._window(NOW), TZ)
        if e["title"] == "Conference"
    )
    assert conf["all_day"] is True
    assert conf["start"] == "2026-07-02"
    assert conf["end"] == "2026-07-05"  # exclusive; covers 07-02, 07-03, 07-04


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


def test_personal_events_are_the_expected_occurrences() -> None:
    # The full set of normalized occurrences, by (title, start) — a mismatch
    # names WHICH event changed instead of a bare "6 != 7". 1 all-day + 1 timed
    # + 4 recurrence occurrences (07-03 EXDATE'd, 07-06 past the window end).
    got = sorted((e["title"], e["start"]) for e in _personal())
    assert got == sorted(
        [
            ("Cabin trip", "2026-07-04"),
            ("Team standup", "2026-07-01T08:30:00-04:00"),
            ("Lunch walk", "2026-07-01T12:00:00-04:00"),
            ("Lunch walk", "2026-07-02T12:00:00-04:00"),
            ("Lunch walk", "2026-07-04T12:00:00-04:00"),
            ("Lunch walk", "2026-07-05T12:00:00-04:00"),
        ]
    )


def test_missing_summary_becomes_empty_title() -> None:
    ics = ICS.replace("SUMMARY:Team standup\n", "")
    # SUMMARY is the field under test here, so selecting by the (now-unique) start
    # is intentional — the title is exactly what we're asserting on.
    standup = next(
        e
        for e in calendar.normalize_events(ics, *calendar._window(NOW), TZ)
        if e["start"] == "2026-07-01T08:30:00-04:00"
    )
    assert standup["title"] == ""


# ── _merge: ordering + shape ──────────────────────────────────────────────────


def test_merge_sorts_all_day_before_same_day_timed() -> None:
    personal: list[AgendaItem] = [
        {
            "start": "2026-07-04T09:00:00-04:00",
            "all_day": False,
            "title": "Brunch",
            "kind": "personal",
        },
    ]
    holiday: list[AgendaItem] = [
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


def _pi(start: str, title: str, kind: Kind) -> AgendaItem:
    return {"start": start, "all_day": True, "title": title, "kind": kind}


@pytest.mark.parametrize(
    ("items", "expected_titles"),
    [
        # Same start, different kind -> kind tiebreak. Sorted alphabetically:
        # holiday < info < observance < personal. Input deliberately scrambled.
        (
            [
                _pi("2026-07-04", "P", "personal"),
                _pi("2026-07-04", "O", "observance"),
                _pi("2026-07-04", "H", "holiday"),
                _pi("2026-07-04", "I", "info"),
            ],
            ["H", "I", "O", "P"],
        ),
        # Same start AND same kind -> title tiebreak (the innermost key).
        (
            [
                _pi("2026-07-04", "Zebra", "personal"),
                _pi("2026-07-04", "Apple", "personal"),
                _pi("2026-07-04", "Mango", "personal"),
            ],
            ["Apple", "Mango", "Zebra"],
        ),
    ],
)
def test_merge_tiebreaks_on_kind_then_title(
    items: list[AgendaItem], expected_titles: list[str]
) -> None:
    # Exercises the (start, kind, title) sort key's SECOND and THIRD dimensions,
    # which the all-day-before-timed test above (a `start`-length difference)
    # never touches.
    block = calendar._merge(True, None, items, [])
    assert [e["title"] for e in block["events"]] == expected_titles


# ── get_calendar: fetch/merge wrapper (network monkeypatched out) ──────────────


def test_get_calendar_ok_merges_personal_and_holidays(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "proton_ics_url", "https://example/secret.ics")
    _patch_fetch_returns(monkeypatch, _personal())
    block = asyncio.run(calendar.get_calendar(NOW))
    assert block["ok"] is True
    # fetched_at is a real wall-clock stamp; assert it carries SOME ISO offset
    # (season-agnostic: EDT -04:00 in summer, EST -05:00 in winter), not a
    # hardcoded EDT that would fail when the suite runs on the other side of DST.
    fetched_at = block["fetched_at"]
    assert fetched_at is not None
    assert re.search(r"[+-]\d{2}:\d{2}$", fetched_at)
    titles = {e["title"] for e in block["events"]}
    assert "Team standup" in titles  # personal merged
    assert "Independence Day" in titles  # offline federal holiday merged (07-04)
    # a personal item carries `end` (the two-sided NotRequired contract: personal
    # events DO carry it; holidays omit it — see the omit test below)
    standup = next(e for e in block["events"] if e["title"] == "Team standup")
    assert "end" in standup
    # flat, sorted in the contract's canonical (start, kind, title) order — not a
    # no-op lexical re-sort, so a kind/title-first regression would be caught.
    keys = [(e["start"], e["kind"], e["title"]) for e in block["events"]]
    assert keys == sorted(keys)


def test_get_calendar_holiday_items_omit_end(monkeypatch: pytest.MonkeyPatch) -> None:
    # `end` is NotRequired: the offline holiday/observance items are single-day
    # and carry no `end` (consumers treat a missing `end` as single-day).
    monkeypatch.setattr(settings, "proton_ics_url", "")
    block = asyncio.run(calendar.get_calendar(NOW))
    holiday = next(e for e in block["events"] if e["title"] == "Independence Day")
    assert "end" not in holiday


def test_get_calendar_proton_failure_still_shows_holidays(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "proton_ics_url", "https://example/secret.ics")
    _patch_fetch_raises(monkeypatch)
    block = asyncio.run(calendar.get_calendar(NOW))
    assert block["ok"] is False  # ok tracks the Proton fetch only
    assert block["fetched_at"] is None
    # holidays still merge in regardless of the Proton outage
    assert any(e["title"] == "Independence Day" for e in block["events"])
    assert all(e["kind"] != "personal" for e in block["events"])


def test_get_calendar_no_url_is_holidays_only(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "proton_ics_url", "")
    block = asyncio.run(calendar.get_calendar(NOW))
    assert block["ok"] is False
    assert block["fetched_at"] is None
    assert any(e["title"] == "Independence Day" for e in block["events"])


def test_get_calendar_proton_failure_keeps_last_good_personal(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Phase 6 per-source last-good: a transient Proton blip must NOT wipe the
    # user's personal events from the agenda. With a last-good doc in hand, the
    # in-window personal events are kept (ok=False) and holidays still merge.
    monkeypatch.setattr(settings, "proton_ics_url", "https://example/secret.ics")
    _patch_fetch_raises(monkeypatch)
    last_good: CalendarBlock = {
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
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # As the window slides during a prolonged outage, last-good personal events
    # that fall out of [today, today+5) must drop (else they bucket into a day
    # the agenda never renders) — matching the live-fetch window filter.
    monkeypatch.setattr(settings, "proton_ics_url", "https://example/secret.ics")
    _patch_fetch_raises(monkeypatch)
    last_good: CalendarBlock = {
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


def test_get_calendar_failure_does_not_leak_url(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    secret = "https://calendar.proton.me/SECRET-TOKEN-xyz?PassphraseKey=DECRYPTKEY"
    monkeypatch.setattr(settings, "proton_ics_url", secret)
    # Mimic a requests exception whose message embeds the full URL + key.
    _patch_fetch_raises(
        monkeypatch,
        lambda url: RuntimeError(f"HTTPSConnectionPool: failed to GET {url}"),
    )
    with caplog.at_level(logging.WARNING):
        asyncio.run(calendar.get_calendar(NOW))
    # A warning MUST have fired (else the not-in assertions below pass vacuously —
    # a silently-swallowed error would be a false green).
    assert caplog.records
    # the secret URL (and its key) must never reach the logs
    assert "SECRET-TOKEN" not in caplog.text
    assert "PassphraseKey" not in caplog.text
    assert "DECRYPTKEY" not in caplog.text
