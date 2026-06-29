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
        {"start": "2026-07-04", "all_day": True, "title": "Independence Day", "kind": "holiday"}
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
        "start": "2026-02-14", "all_day": True, "title": "Valentine's Day", "kind": "observance"
    }
    assert by_title["Groundhog Day"]["kind"] == "observance"


def test_all_ten_observances_present_over_the_year() -> None:
    items = H.get_holidays(date(2026, 1, 1), date(2026, 12, 31))
    observances = sorted(i["title"] for i in items if i["kind"] == "observance")
    assert observances == sorted(
        [
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
        ]
    )


# ── DST markers — kind="info", from zoneinfo (not the holidays lib) ──────────


def test_dst_spring_forward_marker() -> None:
    items = H.get_holidays(date(2026, 3, 1), date(2026, 3, 15))
    dst = [i for i in items if i["kind"] == "info"]
    assert len(dst) == 1
    assert dst[0]["start"] == "2026-03-08"  # spring forward
    assert dst[0]["all_day"] is True
    assert "forward" in dst[0]["title"]


def test_dst_fall_back_marker() -> None:
    items = H.get_holidays(date(2026, 11, 1), date(2026, 11, 2))
    dst = [i for i in items if i["kind"] == "info"]
    assert len(dst) == 1
    assert dst[0]["start"] == "2026-11-01"  # fall back
    assert "back" in dst[0]["title"]


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
