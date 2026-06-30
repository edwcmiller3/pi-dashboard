"""Phase 5 increment 1 — holidays/observances/DST-markers source.

`get_holidays(start, end)` is pure and fully offline (the `holidays` lib +
`zoneinfo`), so the whole suite runs with no network. It emits contract
agenda-items — `{start, all_day, title, kind}` with date-only `start` — for
three tiers: federal US holidays (kind="holiday"), lesser/unofficial
observances (kind="observance"), and DST transitions (kind="info").
"""

from __future__ import annotations

from datetime import date

from app.sources import holidays as H


# ── federal (public) — kind="holiday", actual dates only ─────────────────────


def test_federal_holiday_is_kind_holiday_actual_date() -> None:
    items = H.get_holidays(date(2026, 7, 1), date(2026, 7, 7))
    july4 = [i for i in items if i["title"] == "Independence Day"]
    assert july4 == [
        {
            "start": "2026-07-04",
            "all_day": True,
            "title": "Independence Day",
            "kind": "holiday",
        }
    ]


def test_observed_false_no_shifted_ghost() -> None:
    # 2026-07-04 is a Saturday; with observed=True the lib also emits a
    # 2026-07-03 "(observed)" entry. We want actual dates only.
    items = H.get_holidays(date(2026, 7, 1), date(2026, 7, 7))
    assert not any(i["start"] == "2026-07-03" for i in items)
    assert all("observed" not in i["title"].lower() for i in items)


# ── unofficial — kind="observance" (full set: user chose all 10) ─────────────


def test_unofficial_is_kind_observance() -> None:
    items = H.get_holidays(date(2026, 2, 1), date(2026, 2, 28))
    by_title = {i["title"]: i for i in items}
    assert by_title["Valentine's Day"] == {
        "start": "2026-02-14",
        "all_day": True,
        "title": "Valentine's Day",
        "kind": "observance",
    }
    assert by_title["Groundhog Day"]["kind"] == "observance"


def test_all_observances_present_over_the_year() -> None:
    items = H.get_holidays(date(2026, 1, 1), date(2026, 12, 31))
    observances = sorted(i["title"] for i in items if i["kind"] == "observance")
    assert observances == sorted(
        [
            # unofficial, from the holidays lib — all 10 kept
            "Groundhog Day",
            "Valentine's Day",
            "Saint Patrick's Day",
            "Good Friday",
            "Easter Sunday",
            "Mother's Day",
            "Father's Day",
            "Halloween",
            "Christmas Eve",
            "New Year's Eve",
            # computed cultural extras, absent from the lib (Tax Day excluded)
            "April Fools' Day",
            "Earth Day",
            "Cinco de Mayo",
            "Black Friday",
            "Cyber Monday",
            "Mardi Gras",
            "Pi Day",
            "Talk Like a Pirate Day",
            "May Day",
            "Election Day",  # 2026 is an even (election) year
        ]
    )


# ── computed cultural extras — kind="observance", rule-based (no hardcoded dates)


def test_fixed_date_extras() -> None:
    items = H.get_holidays(date(2026, 1, 1), date(2026, 12, 31))
    by_title = {i["title"]: i for i in items}
    assert by_title["April Fools' Day"] == {
        "start": "2026-04-01",
        "all_day": True,
        "title": "April Fools' Day",
        "kind": "observance",
    }
    assert by_title["Earth Day"]["start"] == "2026-04-22"
    assert by_title["Cinco de Mayo"]["start"] == "2026-05-05"
    assert by_title["Pi Day"]["start"] == "2026-03-14"
    assert by_title["May Day"]["start"] == "2026-05-01"
    assert by_title["Talk Like a Pirate Day"]["start"] == "2026-09-19"


def test_election_day_even_year_is_tuesday_after_first_monday() -> None:
    # 2026 midterm: Nov 1 is a Sunday -> first Monday Nov 2 -> Election Day Nov 3.
    items = H.get_holidays(date(2026, 11, 1), date(2026, 11, 30))
    election = [i for i in items if i["title"] == "Election Day"]
    assert election == [
        {
            "start": "2026-11-03",
            "all_day": True,
            "title": "Election Day",
            "kind": "observance",
        }
    ]


def test_no_election_day_in_odd_year() -> None:
    items = H.get_holidays(date(2027, 1, 1), date(2027, 12, 31))
    assert not any(i["title"] == "Election Day" for i in items)


def test_election_day_not_duplicated_in_presidential_year() -> None:
    # The lib emits its own (quadrennial) Election Day in presidential years; we
    # filter it and own the computation, so 2028 must have exactly one.
    items = H.get_holidays(date(2028, 1, 1), date(2028, 12, 31))
    election = [i for i in items if i["title"] == "Election Day"]
    assert election == [
        {
            "start": "2028-11-07",
            "all_day": True,
            "title": "Election Day",
            "kind": "observance",
        }
    ]


def test_thanksgiving_anchored_extras() -> None:
    # Black Friday = Thanksgiving + 1 day; Cyber Monday = Thanksgiving + 4 days.
    items = H.get_holidays(date(2026, 11, 1), date(2026, 11, 30))
    by_title = {i["title"]: i for i in items}
    assert by_title["Black Friday"]["start"] == "2026-11-27"
    assert by_title["Cyber Monday"]["start"] == "2026-11-30"
    assert by_title["Black Friday"]["kind"] == "observance"


def test_mardi_gras_anchored_on_easter_outside_window() -> None:
    # Mardi Gras = Easter - 47 days. Easter 2026 is Apr 5 (outside this Feb
    # window), but Mardi Gras (Feb 17) must still resolve from the year's anchor.
    items = H.get_holidays(date(2026, 2, 1), date(2026, 2, 28))
    mardi = [i for i in items if i["title"] == "Mardi Gras"]
    assert mardi == [
        {
            "start": "2026-02-17",
            "all_day": True,
            "title": "Mardi Gras",
            "kind": "observance",
        }
    ]


def test_extras_respect_the_window() -> None:
    # Narrow early-April window includes April Fools' but not Earth Day (Apr 22).
    items = H.get_holidays(date(2026, 4, 1), date(2026, 4, 2))
    titles = {i["title"] for i in items}
    assert "April Fools' Day" in titles
    assert "Earth Day" not in titles


# ── DST markers — kind="info", from zoneinfo (not the holidays lib) ──────────


def test_dst_spring_forward_marker() -> None:
    items = H.get_holidays(date(2026, 3, 1), date(2026, 3, 15))
    dst = [i for i in items if i["kind"] == "info"]
    assert len(dst) == 1
    assert dst[0]["start"] == "2026-03-08"  # spring forward
    assert dst[0]["all_day"] is True
    assert dst[0]["title"] == "Daylight Saving Time begins"


def test_dst_fall_back_marker() -> None:
    items = H.get_holidays(date(2026, 11, 1), date(2026, 11, 2))
    dst = [i for i in items if i["kind"] == "info"]
    assert len(dst) == 1
    assert dst[0]["start"] == "2026-11-01"  # fall back
    assert dst[0]["title"] == "Daylight Saving Time ends"


def test_no_dst_marker_in_a_quiet_window() -> None:
    items = H.get_holidays(date(2026, 6, 1), date(2026, 6, 30))
    assert not any(i["kind"] == "info" for i in items)


# ── windowing + ordering ─────────────────────────────────────────────────────


def test_window_excludes_dates_outside_range() -> None:
    items = H.get_holidays(date(2026, 7, 4), date(2026, 7, 4))
    assert {i["start"] for i in items} == {"2026-07-04"}


def test_window_crosses_year_boundary() -> None:
    items = H.get_holidays(date(2026, 12, 30), date(2027, 1, 2))
    by_start = {i["start"]: i for i in items}
    assert by_start["2026-12-31"]["title"] == "New Year's Eve"
    assert by_start["2026-12-31"]["kind"] == "observance"
    assert by_start["2027-01-01"]["title"] == "New Year's Day"
    assert by_start["2027-01-01"]["kind"] == "holiday"


def test_items_sorted_by_date() -> None:
    items = H.get_holidays(date(2026, 1, 1), date(2026, 12, 31))
    starts = [i["start"] for i in items]
    assert starts == sorted(starts)
