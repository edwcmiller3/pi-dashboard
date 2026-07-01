// Unit tests for the pure JS transforms in app.js.
// Run with Node's built-in runner (no deps):  node --test  (from static/)
//
// app.js is an ES module whose bootstrap is guarded by `typeof document`, so
// importing it here runs no DOM/init side effects — only the pure exports load.
//
// Typing: JSDoc @typedefs below document the fixture shapes so a mistyped key
// (e.g. `fetch_at`) shows up as a type mismatch on hover in an editor. `// @ts-check`
// is intentionally NOT enabled: this package ships zero dependencies (no
// node_modules / @types/node), so TS couldn't resolve the `node:*` builtins and
// would flag spurious "cannot find module" errors. The typedefs still give hover
// types without that noise. The DOM/render/fetch half of app.js needs a DOM to
// test and is deliberately out of scope for this dep-free suite.
//
// Clock-dependent tests (dayLabel "Today") freeze time via `t.mock.timers` so
// they can't flake when the run crosses local midnight.

import test, { mock } from "node:test";
import assert from "node:assert/strict";

import {
  localParts,
  to12,
  fmtCompact,
  fmtLong,
  localDate,
  isSameDay,
  localDayKey,
  dayRolledOver,
  groupByDay,
  splitColumns,
  withTodayGroup,
  hasPersonalEvents,
  dayLabel,
  pickUpdated,
  inBlackout,
} from "./app.js";

/**
 * @typedef {{ start: string, title?: string, kind?: string, all_day?: boolean }} AgendaEvent
 * @typedef {{ ok: boolean, fetched_at: string | null }} SourceBlock
 * @typedef {{ date: string, items: any[] }} DayGroup
 */

// ── localParts ───────────────────────────────────────────────────────────────

test("localParts: datetime with offset -> date + local wall-clock (no re-zoning)", () => {
  assert.deepEqual(localParts("2026-06-28T08:30:00-04:00"), {
    date: "2026-06-28",
    time: { hh: 8, mm: 30 },
  });
});

test("localParts: a DIFFERENT offset still reads the literal local part", () => {
  // 08:30 stays 08:30 regardless of the +09:00 zone — we do NOT re-zone.
  assert.deepEqual(localParts("2026-06-28T08:30:00+09:00").time, { hh: 8, mm: 30 });
});

test("localParts: date-only -> time null", () => {
  assert.deepEqual(localParts("2026-07-04"), { date: "2026-07-04", time: null });
});

test("localParts: Z (UTC) suffix reads the literal wall-clock", () => {
  assert.deepEqual(localParts("2026-06-28T23:05:00Z").time, { hh: 23, mm: 5 });
});

test("localParts: fractional seconds do not shift hh/mm parsing", () => {
  assert.deepEqual(localParts("2026-06-28T07:09:30.250-04:00").time, { hh: 7, mm: 9 });
});

test("localParts: midnight", () => {
  assert.deepEqual(localParts("2026-06-28T00:00:00-04:00").time, { hh: 0, mm: 0 });
});

// ── to12 ─────────────────────────────────────────────────────────────────────

test("to12: 0 -> 12 AM", () => assert.deepEqual(to12(0), { h: 12, ampm: "AM" }));
test("to12: 12 -> 12 PM", () => assert.deepEqual(to12(12), { h: 12, ampm: "PM" }));
test("to12: 13 -> 1 PM", () => assert.deepEqual(to12(13), { h: 1, ampm: "PM" }));
test("to12: 23 -> 11 PM", () => assert.deepEqual(to12(23), { h: 11, ampm: "PM" }));
test("to12: 11 -> 11 AM", () => assert.deepEqual(to12(11), { h: 11, ampm: "AM" }));

// ── fmtCompact / fmtLong ─────────────────────────────────────────────────────

test("fmtCompact: padded minutes + lowercase meridiem suffix", () => {
  assert.equal(fmtCompact({ hh: 8, mm: 30 }), "8:30a");
  assert.equal(fmtCompact({ hh: 12, mm: 0 }), "12:00p");
  assert.equal(fmtCompact({ hh: 0, mm: 5 }), "12:05a");
  assert.equal(fmtCompact({ hh: 21, mm: 15 }), "9:15p");
});

test("fmtLong: padded minutes + uppercase meridiem", () => {
  assert.equal(fmtLong({ hh: 9, mm: 40 }), "9:40 AM");
  assert.equal(fmtLong({ hh: 13, mm: 5 }), "1:05 PM");
  assert.equal(fmtLong({ hh: 0, mm: 0 }), "12:00 AM");
});

// ── localDate (no UTC shift) ─────────────────────────────────────────────────

test("localDate: builds a LOCAL calendar date, no UTC back-shift", () => {
  const d = localDate("2026-07-04");
  assert.equal(d.getFullYear(), 2026);
  assert.equal(d.getMonth(), 6); // July (0-based)
  assert.equal(d.getDate(), 4); // would be the 3rd if parsed as UTC midnight
});

// ── isSameDay ────────────────────────────────────────────────────────────────

test("isSameDay: same Y/M/D true regardless of time", () => {
  assert.equal(isSameDay(new Date(2026, 5, 28, 8), new Date(2026, 5, 28, 23)), true);
});

test("isSameDay: different day false", () => {
  assert.equal(isSameDay(new Date(2026, 5, 28), new Date(2026, 5, 29)), false);
});

// ── localDayKey / dayRolledOver (midnight rollover) ──────────────────────────

test("localDayKey: zero-pads month/day to YYYY-MM-DD (local components)", () => {
  // Jan 5 2026, late evening — must read the LOCAL date, zero-padded.
  assert.equal(localDayKey(new Date(2026, 0, 5, 23, 59)), "2026-01-05");
  assert.equal(localDayKey(new Date(2026, 11, 31, 0, 0)), "2026-12-31");
});

test("dayRolledOver: true only when the day changes and prev is known", () => {
  assert.equal(dayRolledOver(null, "2026-07-01"), false); // first run -> no reload
  assert.equal(dayRolledOver("2026-07-01", "2026-07-01"), false); // same day
  assert.equal(dayRolledOver("2026-06-30", "2026-07-01"), true); // midnight roll
});

// ── groupByDay ───────────────────────────────────────────────────────────────

test("groupByDay: groups consecutive same-day events under one date", () => {
  /** @type {AgendaEvent[]} */
  const events = [
    { start: "2026-06-28T08:30:00-04:00", title: "a" },
    { start: "2026-06-28T10:00:00-04:00", title: "b" },
    { start: "2026-06-29T11:00:00-04:00", title: "c" },
    { start: "2026-06-30", title: "d" },
  ];
  const groups = groupByDay(events);
  assert.deepEqual(
    groups.map((g) => g.date),
    ["2026-06-28", "2026-06-29", "2026-06-30"],
  );
  assert.deepEqual(
    groups[0].items.map((e) => e.title),
    ["a", "b"],
  );
});

test("groupByDay: preserves ENCOUNTER order and folds an interleaved repeat day", () => {
  // The input is deliberately NOT date-sorted, and day A reappears after day B.
  // This distinguishes "preserves first-appearance order" from "sorts by date"
  // (the old pre-sorted fixture couldn't) AND proves a reappearing day folds
  // into its existing group rather than starting a new one.
  /** @type {AgendaEvent[]} */
  const events = [
    { start: "2026-06-29T09:00:00-04:00", title: "a" }, // day A first
    { start: "2026-06-28T10:00:00-04:00", title: "b" }, // day B (earlier DATE, later input)
    { start: "2026-06-29T11:00:00-04:00", title: "c" }, // day A again, interleaved
  ];
  const groups = groupByDay(events);
  // encounter order (A before B), NOT chronological
  assert.deepEqual(
    groups.map((g) => g.date),
    ["2026-06-29", "2026-06-28"],
  );
  // the reappearing day-A event lands in the existing A group, order kept
  assert.deepEqual(
    groups[0].items.map((e) => e.title),
    ["a", "c"],
  );
});

test("groupByDay: empty -> empty", () => {
  assert.deepEqual(groupByDay([]), []);
});

// ── splitColumns ─────────────────────────────────────────────────────────────

/** @type {(date: string, n: number) => DayGroup} */
const dayGroup = (date, n) => ({ date, items: Array.from({ length: n }, (_, i) => i) });

test("splitColumns: 0 groups -> both empty", () => {
  assert.deepEqual(splitColumns([]), [[], []]);
});

test("splitColumns: 1 group -> all in col1, col2 empty", () => {
  const groups = [dayGroup("d1", 3)];
  assert.deepEqual(splitColumns(groups), [groups, []]);
});

test("splitColumns: 2 groups -> today (first) alone in col1, rest in col2", () => {
  const groups = [dayGroup("d1", 2), dayGroup("d2", 2)];
  const [c1, c2] = splitColumns(groups);
  assert.equal(c1.length, 1);
  assert.equal(c2.length, 1);
  assert.equal(c1[0].date, "d1");
  assert.equal(c2[0].date, "d2");
});

test("splitColumns: a light today still gets col1 to itself (no balancing)", () => {
  // The old height-balanced rule would pull d2 up beside a light d1; the v4
  // rule keeps today alone regardless of how few events it has.
  const groups = [dayGroup("d1", 1), dayGroup("d2", 100)];
  const [c1, c2] = splitColumns(groups);
  assert.deepEqual(
    c1.map((x) => x.date),
    ["d1"],
  );
  assert.deepEqual(
    c2.map((x) => x.date),
    ["d2"],
  );
});

test("splitColumns: today alone in col1, ALL upcoming days stack in col2, order preserved", () => {
  const groups = [dayGroup("d1", 1), dayGroup("d2", 1), dayGroup("d3", 1), dayGroup("d4", 1)];
  const [c1, c2] = splitColumns(groups);
  assert.deepEqual(
    c1.map((x) => x.date),
    ["d1"],
  );
  assert.deepEqual(
    c2.map((x) => x.date),
    ["d2", "d3", "d4"],
  );
});

test("splitColumns: does not mutate the input array", () => {
  const groups = [dayGroup("d1", 1), dayGroup("d2", 1), dayGroup("d3", 1)];
  const before = groups.map((x) => x.date);
  splitColumns(groups);
  assert.deepEqual(
    groups.map((x) => x.date),
    before,
  );
});

// ── withTodayGroup (guarantee today leads the agenda, for the quiet-day state) ─

/** @type {(kind: string) => AgendaEvent} */
const agendaItem = (kind) => ({ kind, start: "x", all_day: false, title: kind });

test("withTodayGroup: today already first -> returned equal (contents unchanged)", () => {
  const groups = [dayGroup("2026-06-30", 2), dayGroup("2026-07-01", 1)];
  // Assert the CONTENTS are returned as-is (behavior), not reference identity —
  // a refactor that returned a shallow copy would still be correct.
  assert.deepEqual(withTodayGroup(groups, "2026-06-30"), groups);
});

test("withTodayGroup: today absent -> prepends an empty today group", () => {
  const groups = [dayGroup("2026-07-01", 1)];
  const out = withTodayGroup(groups, "2026-06-30");
  assert.deepEqual(
    out.map((x) => x.date),
    ["2026-06-30", "2026-07-01"],
  );
  assert.deepEqual(out[0].items, []); // synthesized today has no events
});

test("withTodayGroup: no events at all -> a lone empty today group", () => {
  const out = withTodayGroup([], "2026-06-30");
  assert.deepEqual(out, [{ date: "2026-06-30", items: [] }]);
});

test("withTodayGroup: does not mutate the input array", () => {
  const groups = [dayGroup("2026-07-01", 1)];
  withTodayGroup(groups, "2026-06-30");
  assert.equal(groups.length, 1);
});

// ── hasPersonalEvents (the quiet-day predicate) ───────────────────────────────

test("hasPersonalEvents: true when a personal event is present", () => {
  assert.equal(hasPersonalEvents([agendaItem("holiday"), agendaItem("personal")]), true);
});

test("hasPersonalEvents: false for only holiday/observance/info", () => {
  assert.equal(
    hasPersonalEvents([agendaItem("holiday"), agendaItem("observance"), agendaItem("info")]),
    false,
  );
});

test("hasPersonalEvents: false for an empty day", () => {
  assert.equal(hasPersonalEvents([]), false);
});

// ── dayLabel (time frozen so "Today" can't flake across midnight) ─────────────

test("dayLabel: today -> isToday + 'Today'", (t) => {
  // Freeze the clock so localDayKey() and dayLabel()'s internal `new Date()`
  // observe the same instant — no midnight-crossing race.
  t.mock.timers.enable({ apis: ["Date"] });
  t.mock.timers.setTime(Date.UTC(2026, 6, 1, 16, 0, 0));
  const label = dayLabel(localDayKey()); // localDayKey reads the frozen local day
  assert.equal(label.isToday, true);
  assert.equal(label.dname, "Today");
});

test("dayLabel(localDayKey()) is today -> the synthesized quiet-day group labels as 'Today'", (t) => {
  // The quiet-day path hinges on withTodayGroup's synthesized group (date =
  // localDayKey()) resolving to isToday through dayLabel — guard that coupling,
  // deterministically, with a frozen clock.
  t.mock.timers.enable({ apis: ["Date"] });
  t.mock.timers.setTime(Date.UTC(2026, 11, 31, 18, 0, 0));
  const label = dayLabel(localDayKey());
  assert.equal(label.isToday, true);
  assert.equal(label.dname, "Today");
});

test("dayLabel: a non-today date -> isToday false, weekday name (not 'Today')", () => {
  // A far-future date is deterministically not "today" without freezing time.
  const future = dayLabel("2099-01-02");
  assert.equal(future.isToday, false);
  assert.notEqual(future.dname, "Today");
  assert.equal(typeof future.dname, "string");
  assert.ok(future.dname.length > 0);
});

// ── pickUpdated ("Updated" = OLDEST ok source = min) ──────────────────────────

test("pickUpdated: no sources -> null", () => {
  assert.equal(pickUpdated([]), null);
});

test("pickUpdated: no ok source with a stamp -> null", () => {
  assert.equal(
    pickUpdated([
      { ok: false, fetched_at: "2026-07-01T09:00:00-04:00" },
      { ok: true, fetched_at: null },
    ]),
    null,
  );
});

test("pickUpdated: single ok source -> its stamp", () => {
  assert.equal(
    pickUpdated([{ ok: true, fetched_at: "2026-07-01T09:40:00-04:00" }]),
    "2026-07-01T09:40:00-04:00",
  );
});

test("pickUpdated: returns the OLDEST (min) ok stamp, not the newest", () => {
  // "Updated X" must mean EVERY ok source is fresh as of at least X — so the
  // oldest wins, never the most recent (which would over-claim freshness).
  const got = pickUpdated([
    { ok: true, fetched_at: "2026-07-01T09:40:00-04:00" }, // weather, newer
    { ok: true, fetched_at: "2026-07-01T09:38:00-04:00" }, // calendar, older
  ]);
  assert.equal(got, "2026-07-01T09:38:00-04:00");
});

test("pickUpdated: equal timestamps -> that stamp (stable, no spurious choice)", () => {
  const s = "2026-07-01T09:00:00-04:00";
  assert.equal(pickUpdated([{ ok: true, fetched_at: s }, { ok: true, fetched_at: s }]), s);
});

test("pickUpdated: an unparseable stamp never wins over a valid one (any order)", () => {
  // Date.parse("garbage") is NaN and every `<` with NaN is false, so a bad stamp
  // seen FIRST used to win the min and never be beaten. It must be ignored
  // regardless of position — assert both orderings pick the valid stamp.
  const good = "2026-07-01T09:00:00-04:00";
  assert.equal(
    pickUpdated([{ ok: true, fetched_at: "garbage" }, { ok: true, fetched_at: good }]),
    good,
  );
  assert.equal(
    pickUpdated([{ ok: true, fetched_at: good }, { ok: true, fetched_at: "garbage" }]),
    good,
  );
});

test("pickUpdated: compares by instant across mixed offsets, excludes !ok", () => {
  // 12:30Z (= 08:30-04:00) is the earlier instant than 09:00-04:00 (= 13:00Z),
  // even though its local wall-clock reads later — compare epochs, not strings.
  const got = pickUpdated([
    { ok: true, fetched_at: "2026-07-01T09:00:00-04:00" },
    { ok: true, fetched_at: "2026-07-01T12:30:00+00:00" },
    { ok: false, fetched_at: "2026-07-01T00:00:00-04:00" }, // stale -> ignored
  ]);
  assert.equal(got, "2026-07-01T12:30:00+00:00");
});

// ── inBlackout (nightly 1a–6a wall-clock blackout window) ────────────────────

// A local Date at hour h (minute m) on an arbitrary day — the window is
// hour-grained and day-agnostic, so the calendar date is irrelevant.
/** @type {(h: number, m?: number) => Date} */
const atHour = (h, m = 0) => new Date(2026, 5, 30, h, m);

test("inBlackout: false just before the window opens (00:59)", () => {
  assert.equal(inBlackout(atHour(0, 59)), false);
});

test("inBlackout: true exactly at the 01:00 open boundary (inclusive)", () => {
  assert.equal(inBlackout(atHour(1, 0)), true);
});

test("inBlackout: true mid-window at 03:00 — the Phase-8 reboot lands in black", () => {
  // The 03:00 nightly reboot is INSIDE the window; a fresh page load at 03:00
  // must come back to black, which is exactly why this is wall-clock-driven and
  // not a timer counting from boot.
  assert.equal(inBlackout(atHour(3, 0)), true);
});

test("inBlackout: true at the last in-window minute (05:59)", () => {
  assert.equal(inBlackout(atHour(5, 59)), true);
});

test("inBlackout: false exactly at the 06:00 close boundary (exclusive)", () => {
  assert.equal(inBlackout(atHour(6, 0)), false);
});

test("inBlackout: false during the day and evening", () => {
  assert.equal(inBlackout(atHour(0, 0)), false); // midnight, before the window
  assert.equal(inBlackout(atHour(12, 0)), false);
  assert.equal(inBlackout(atHour(23, 0)), false);
});

test("inBlackout: a window that wraps past midnight (start > end)", () => {
  // The shipped 1a–6a window doesn't wrap, but the function supports it: a
  // 22:00–06:00 window is in-blackout late evening AND early morning, not midday.
  assert.equal(inBlackout(atHour(23, 0), 22, 6), true);
  assert.equal(inBlackout(atHour(5, 0), 22, 6), true);
  assert.equal(inBlackout(atHour(12, 0), 22, 6), false);
});

test("inBlackout: wrapped-window boundaries (22:00 inclusive, 06:00 exclusive)", () => {
  // The exact edges of the wrapped path — the ones most likely to be off by one,
  // and untested before (the wrap test above only checked interior hours).
  assert.equal(inBlackout(atHour(21, 59), 22, 6), false); // just before open
  assert.equal(inBlackout(atHour(22, 0), 22, 6), true); // inclusive open
  assert.equal(inBlackout(atHour(5, 59), 22, 6), true); // last in-window minute
  assert.equal(inBlackout(atHour(6, 0), 22, 6), false); // exclusive close
});

test("inBlackout: an empty window (start === end) is never in blackout", () => {
  assert.equal(inBlackout(atHour(3, 0), 6, 6), false);
});

// mock.timers auto-reset per test via t.mock, but reset the top-level mock too in
// case any test used it directly.
test.after(() => mock.timers.reset());
