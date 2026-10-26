"""Calendar adapter tests.

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
from collections.abc import Callable, Iterator
from datetime import date, datetime
from typing import NoReturn
from zoneinfo import ZoneInfo

import pytest

from app.config import settings
from app.contract import AgendaItem, CalendarBlock, Kind
from app.sources import calendar

TZ = ZoneInfo("America/New_York")
# Deterministic reference: Wed 2026-07-01 09:00 EDT. Window = [07-01, 07-06).
NOW = datetime(2026, 7, 1, 9, 0, tzinfo=TZ)

# The `_fetch_personal` stubs below mirror its exact signature (not `*args: Any`)
# so a stub that drifts from the seam fails the type-check.

# Synthetic Proton-shaped feed: an all-day event, a timed event, a DAILY
# recurrence with one EXDATE-excluded occurrence, and one event outside the
# window. VTIMEZONE rides along like the real feed.
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


# A weekly 10:00-local event straddling the 2026-11-01 DST end (EDT->EST).
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


# A multi-day all-day event that began before the window but overlaps it (a trip
# in progress), alongside an in-window event.
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
    """Replace `_fetch_personal` with a typed stub that raises. `make_error`
    builds the exception from the URL (the secret-leak test embeds it)."""

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
    # The lib synthesizes DTEND == DTSTART (a zero-duration interval).
    walks = [e for e in _personal() if e["title"] == "Lunch walk"]
    assert walks  # sanity: the recurrence produced occurrences
    assert all(e["end"] == e["start"] for e in walks)


def test_all_day_single_day_end_is_exclusive_next_day() -> None:
    # No DTEND: the lib synthesizes the exclusive next day.
    cabin = next(e for e in _personal() if e["title"] == "Cabin trip")
    assert cabin["start"] == "2026-07-04"
    assert cabin["end"] == "2026-07-05"  # exclusive; covers the dates [07-04, 07-05)


def test_multiday_all_day_expands_to_one_item_per_covered_day() -> None:
    # So it shows on every day it covers; each emitted day is itself half-open.
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
    conf = [
        e
        for e in calendar.normalize_events(ics, *calendar._window(NOW), TZ)
        if e["title"] == "Conference"
    ]
    assert all(e["all_day"] is True and e["kind"] == "personal" for e in conf)
    assert [(e["start"], e["end"]) for e in conf] == [
        ("2026-07-02", "2026-07-03"),
        ("2026-07-03", "2026-07-04"),
        ("2026-07-04", "2026-07-05"),
    ]


# ── _covered_days: the pure multi-day clamp/expand core ───────────────────────

# Window dates matching NOW's `[07-01, 07-06)` (window_hi is exclusive).
_WLO = date(2026, 7, 1)
_WHI = date(2026, 7, 6)


def test_covered_days_single_day_span_is_one_day() -> None:
    assert calendar._covered_days(date(2026, 7, 4), date(2026, 7, 5), _WLO, _WHI) == [
        date(2026, 7, 4)
    ]


def test_covered_days_multiday_fully_in_window_excludes_end() -> None:
    # [07-02, 07-05) -> 07-02, 07-03, 07-04 (the exclusive end day drops out).
    assert calendar._covered_days(date(2026, 7, 2), date(2026, 7, 5), _WLO, _WHI) == [
        date(2026, 7, 2),
        date(2026, 7, 3),
        date(2026, 7, 4),
    ]


def test_covered_days_clamps_inprogress_start_to_window_lo() -> None:
    # Began 06-28 (pre-window), ends 07-03 -> clamped to Today (07-01) forward.
    assert calendar._covered_days(date(2026, 6, 28), date(2026, 7, 3), _WLO, _WHI) == [
        date(2026, 7, 1),
        date(2026, 7, 2),
    ]


def test_covered_days_clamps_span_running_past_window_hi() -> None:
    # 07-04 .. 07-10 -> clamped to the last in-window day (window_hi exclusive).
    assert calendar._covered_days(date(2026, 7, 4), date(2026, 7, 10), _WLO, _WHI) == [
        date(2026, 7, 4),
        date(2026, 7, 5),
    ]


def test_covered_days_entirely_outside_window_is_empty() -> None:
    assert (
        calendar._covered_days(date(2026, 6, 20), date(2026, 6, 25), _WLO, _WHI) == []
    )


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
    # Wall-clock stays 10:00 while the emitted offset flips -04:00 -> -05:00.
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
    assert all(s[11:16] == "10:00" for s in syncs)


def test_event_outside_window_is_excluded() -> None:
    assert all(e["title"] != "Way out there" for e in _personal())


def test_inprogress_multiday_all_day_is_clamped_into_window() -> None:
    # A trip in progress must show today, not bucket under an unrendered past day.
    # Vacation is [06-28, 07-03); intersected with [07-01, 07-06) -> 07-01, 07-02.
    items = calendar.normalize_events(MULTIDAY_ICS, *calendar._window(NOW), TZ)
    vacation = sorted(e["start"] for e in items if e["title"] == "Vacation")
    assert vacation == ["2026-07-01", "2026-07-02"]  # clamped to Today forward
    assert all(
        e["end"] == "2026-07-02" if e["start"] == "2026-07-01" else True
        for e in items
        if e["title"] == "Vacation"
    )  # each emitted day stays half-open [day, day+1)
    titles = {e["title"] for e in items}
    assert "Mid-week lunch" in titles  # single-day 07-02, in window - still shown
    assert all(e["start"][:10] >= "2026-07-01" for e in items)  # nothing pre-window


def test_personal_events_are_the_expected_occurrences() -> None:
    # Compared by (title, start) so a mismatch names the event, not a bare count.
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


def test_naive_dtstart_is_localized_to_display_tz() -> None:
    # A floating DTSTART (no TZID, no Z) still yields an offset-bearing start.
    ics = """\
BEGIN:VCALENDAR
VERSION:2.0
PRODID:-//Proton//Calendar//EN
BEGIN:VEVENT
UID:floating@test
DTSTART:20260701T083000
SUMMARY:Floating time
END:VEVENT
END:VCALENDAR
"""
    floating = next(
        e
        for e in calendar.normalize_events(ics, *calendar._window(NOW), TZ)
        if e["title"] == "Floating time"
    )
    assert floating["start"] == "2026-07-01T08:30:00-04:00"  # EDT offset attached
    assert floating["all_day"] is False


def test_missing_summary_becomes_empty_title() -> None:
    ics = ICS.replace("SUMMARY:Team standup\n", "")
    # Select by start, since the title is what's under test.
    standup = next(
        e
        for e in calendar.normalize_events(ics, *calendar._window(NOW), TZ)
        if e["start"] == "2026-07-01T08:30:00-04:00"
    )
    assert standup["title"] == ""


# ── _read_capped: size cap, secret-free errors, UTF-8 decode ──────────────────

# The real feed URL is a bearer credential; the error-message assertions below
# check it never leaks.
_SECRET_URL = "https://calendar.example/SECRET-TOKEN/calendar.ics?PassphraseKey=KEY"


class _FakeResponse:
    """`requests.Response` stand-in for the surface `_read_capped` touches.
    `encoding` defaults to ISO-8859-1, what requests derives for a charset-less
    `text/*` header, so the decode tests cover that case."""

    def __init__(
        self,
        body: bytes,
        headers: dict[str, str] | None = None,
        encoding: str | None = "ISO-8859-1",
    ) -> None:
        self._body = body
        self.headers = headers or {}
        self.encoding = encoding

    def __enter__(self) -> _FakeResponse:
        return self

    def __exit__(self, *exc: object) -> None:
        return None

    def raise_for_status(self) -> None:
        return None

    def iter_content(self, chunk_size: int) -> Iterator[bytes]:
        for i in range(0, len(self._body), chunk_size):
            yield self._body[i : i + chunk_size]


def _patch_session_get(monkeypatch: pytest.MonkeyPatch, resp: _FakeResponse) -> None:
    def fake_get(url: str, *, timeout: int, stream: bool) -> _FakeResponse:
        return resp

    monkeypatch.setattr(calendar._SESSION, "get", fake_get)


def test_read_capped_returns_body_under_cap(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_session_get(monkeypatch, _FakeResponse(b"BEGIN:VCALENDAR\r\n"))
    assert calendar._read_capped(_SECRET_URL) == "BEGIN:VCALENDAR\r\n"


def test_read_capped_decodes_utf8_despite_charsetless_header(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # RFC 5545 mandates UTF-8; honoring `resp.encoding` would mojibake the body.
    _patch_session_get(monkeypatch, _FakeResponse("SUMMARY:Café ☕\r\n".encode()))
    assert calendar._read_capped(_SECRET_URL) == "SUMMARY:Café ☕\r\n"


def test_read_capped_replaces_undecodable_bytes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # One bad byte must not drop the whole calendar.
    _patch_session_get(monkeypatch, _FakeResponse(b"SUMMARY:Caf\xe9\r\n"))
    assert calendar._read_capped(_SECRET_URL) == "SUMMARY:Caf�\r\n"


def test_read_capped_rejects_oversized_content_length(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    declared = str(calendar._MAX_ICS_BYTES + 1)
    _patch_session_get(
        monkeypatch, _FakeResponse(b"", headers={"Content-Length": declared})
    )
    with pytest.raises(ValueError) as exc_info:
        calendar._read_capped(_SECRET_URL)
    message = str(exc_info.value)
    assert declared in message and str(calendar._MAX_ICS_BYTES) in message  # sizes only
    assert "SECRET-TOKEN" not in message and "PassphraseKey" not in message


def test_read_capped_cuts_off_lying_content_length_mid_stream(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    oversized = b"X" * (calendar._MAX_ICS_BYTES + 1)
    _patch_session_get(
        monkeypatch, _FakeResponse(oversized, headers={"Content-Length": "42"})
    )
    with pytest.raises(ValueError) as exc_info:
        calendar._read_capped(_SECRET_URL)
    message = str(exc_info.value)
    assert str(calendar._MAX_ICS_BYTES) in message  # sizes only, never the URL
    assert "SECRET-TOKEN" not in message and "PassphraseKey" not in message


def test_read_capped_ignores_non_numeric_content_length(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # A junk Content-Length can't crash the pre-check; the mid-stream cap still
    # guards the actual body.
    _patch_session_get(
        monkeypatch,
        _FakeResponse(b"BEGIN:VCALENDAR\r\n", headers={"Content-Length": "garbage"}),
    )
    assert calendar._read_capped(_SECRET_URL) == "BEGIN:VCALENDAR\r\n"


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
    assert [e["title"] for e in block["events"]] == ["Independence Day", "Brunch"]
    assert block["ok"] is True
    assert block["fetched_at"] == "2026-07-01T09:00:00-04:00"


def _pi(start: str, title: str, kind: Kind) -> AgendaItem:
    return {"start": start, "all_day": True, "title": title, "kind": kind}


@pytest.mark.parametrize(
    ("items", "expected_titles"),
    [
        # Kind sorts alphabetically: holiday < info < observance < personal.
        (
            [
                _pi("2026-07-04", "P", "personal"),
                _pi("2026-07-04", "O", "observance"),
                _pi("2026-07-04", "H", "holiday"),
                _pi("2026-07-04", "I", "info"),
            ],
            ["H", "I", "O", "P"],
        ),
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
    # fetched_at is real wall-clock time, so match any offset, not EDT - the
    # suite must pass on either side of DST.
    fetched_at = block["fetched_at"]
    assert fetched_at is not None
    assert re.search(r"[+-]\d{2}:\d{2}$", fetched_at)
    titles = {e["title"] for e in block["events"]}
    assert "Team standup" in titles  # personal merged
    assert "Independence Day" in titles  # offline federal holiday merged (07-04)
    standup = next(e for e in block["events"] if e["title"] == "Team standup")
    assert "end" in standup
    keys = [(e["start"], e["kind"], e["title"]) for e in block["events"]]
    assert keys == sorted(keys)


def test_get_calendar_holiday_items_omit_end(monkeypatch: pytest.MonkeyPatch) -> None:
    # Consumers treat a missing `end` as single-day.
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
    # A transient Proton blip must not wipe personal events from the agenda.
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
            # Holidays are recomputed every tick, so last-good ones must not carry.
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
    # During a long outage the window slides; stale events would bucket into a
    # day the agenda never renders.
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
    # Else the not-in assertions below pass vacuously.
    assert caplog.records
    assert "SECRET-TOKEN" not in caplog.text
    assert "PassphraseKey" not in caplog.text
    assert "DECRYPTKEY" not in caplog.text
