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
  localInstant,
  nextUp,
  pastIndexes,
  dayLabel,
  pickUpdated,
  fmtHiLo,
  planDayFit,
  planColumnFit,
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
  // A height-balanced rule would pull d2 up beside a light d1; this rule
  // keeps today alone regardless of how few events it has.
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

// ── localInstant (local wall-clock from an ISO string, no re-zoning) ──────────

test("localInstant: datetime -> a local Date at the encoded wall-clock (offset ignored)", () => {
  // The -04:00 offset is NOT reinterpreted — the local components are read as-is.
  const d = localInstant("2026-07-01T14:30:00-04:00");
  assert.equal(d.getFullYear(), 2026);
  assert.equal(d.getMonth(), 6); // July (0-based)
  assert.equal(d.getDate(), 1);
  assert.equal(d.getHours(), 14);
  assert.equal(d.getMinutes(), 30);
});

test("localInstant: date-only -> local midnight", () => {
  const d = localInstant("2026-07-04");
  assert.equal(d.getHours(), 0);
  assert.equal(d.getMinutes(), 0);
  assert.equal(d.getDate(), 4);
});

// ── nextUp ("next up" emphasis: index of earliest not-past timed personal ev) ──

// 14:00 local on 2026-07-01 — the reference "now" for the cases below.
const NOW = new Date(2026, 6, 1, 14, 0);
// A timed personal event on NOW's day; hh:mm are local wall-clock (offset is
// cosmetic — localInstant reads the literal parts).
/** @param {number} sh @param {number} eh @returns {AgendaEvent & {end: string}} */
const timed = (sh, eh) => ({
  start: `2026-07-01T${String(sh).padStart(2, "0")}:00:00-04:00`,
  end: `2026-07-01T${String(eh).padStart(2, "0")}:00:00-04:00`,
  all_day: false,
  title: "e",
  kind: "personal",
});

test("nextUp: empty day -> -1 (no emphasis)", () => {
  assert.equal(nextUp([], NOW), -1);
});

test("nextUp: only all-day / holiday items -> -1 (timed personal only)", () => {
  const items = [
    { start: "2026-07-01", end: "2026-07-02", all_day: true, title: "Trip", kind: "personal" },
    { start: "2026-07-01", all_day: true, title: "Holiday", kind: "holiday" },
  ];
  assert.equal(nextUp(items, NOW), -1);
});

test("nextUp: all events already past -> -1", () => {
  // both end before 14:00.
  assert.equal(nextUp([timed(9, 10), timed(11, 12)], NOW), -1);
});

test("nextUp: a soonest upcoming event -> its index", () => {
  // past 9–10, then upcoming 15–16.
  assert.equal(nextUp([timed(9, 10), timed(15, 16)], NOW), 1);
});

test("nextUp: an in-progress event is picked over a later upcoming", () => {
  // 13–15 straddles 14:00 (in progress); 15–16 is upcoming. First not-past = 0.
  assert.equal(nextUp([timed(13, 15), timed(15, 16)], NOW), 0);
});

test("nextUp: in-progress wins even when a past event precedes it", () => {
  // sorted: past 9–10, in-progress 13–15, upcoming 16–17 -> the in-progress one.
  assert.equal(nextUp([timed(9, 10), timed(13, 15), timed(16, 17)], NOW), 1);
});

test("nextUp: a long in-progress meeting stays picked though a later event exists", () => {
  // 9–17 is still running at 14:00 (keys off END, the half-open [start,end)); the
  // 15–16 event does NOT steal emphasis — you're still in the long meeting.
  assert.equal(nextUp([timed(9, 17), timed(15, 16)], NOW), 0);
});

test("nextUp: all-day personal items are skipped in favor of the next timed one", () => {
  const items = [
    { start: "2026-07-01", end: "2026-07-02", all_day: true, title: "Trip", kind: "personal" },
    timed(15, 16),
  ];
  assert.equal(nextUp(items, NOW), 1);
});

test("nextUp: an event with no end is an instant — upcoming before it, past after", () => {
  const upcoming = { start: "2026-07-01T15:00:00-04:00", all_day: false, title: "e", kind: "personal" };
  const past = { start: "2026-07-01T13:00:00-04:00", all_day: false, title: "e", kind: "personal" };
  assert.equal(nextUp([upcoming], NOW), 0);
  assert.equal(nextUp([past], NOW), -1);
});

// ── pastIndexes (roll-off: which of today's events MAY hide on overflow) ──────

test("pastIndexes: empty day -> no candidates", () => {
  assert.deepEqual(pastIndexes([], NOW), []);
});

test("pastIndexes: all upcoming -> no candidates", () => {
  assert.deepEqual(pastIndexes([timed(15, 16), timed(17, 18)], NOW), []);
});

test("pastIndexes: past events -> their indices, ascending (oldest first)", () => {
  // 9–10 and 11–12 are over at 14:00; 15–16 is upcoming.
  assert.deepEqual(pastIndexes([timed(9, 10), timed(11, 12), timed(15, 16)], NOW), [0, 1]);
});

test("pastIndexes: an in-progress event is NOT past (half-open [start,end))", () => {
  // 13–15 straddles 14:00 — it's the event being highlighted, never rolled off.
  assert.deepEqual(pastIndexes([timed(13, 15)], NOW), []);
});

test("pastIndexes: past exactly AT its end instant (now === end -> over)", () => {
  // Half-open: the event no longer covers 14:00 when it ends at 14:00.
  assert.deepEqual(pastIndexes([timed(12, 14)], NOW), [0]);
});

test("pastIndexes: past events need not be a prefix (long in-progress first)", () => {
  // 9–17 is still running at 14:00 but the LATER-sorted 10–11 is already over —
  // the candidate set is by pastness, not by position in the list.
  assert.deepEqual(pastIndexes([timed(9, 17), timed(10, 11)], NOW), [1]);
});

test("pastIndexes: all-day personal items never roll off, even when ended", () => {
  // A trip that ended YESTERDAY (end 2026-07-01 exclusive) is still day context.
  const trip = { start: "2026-06-30", end: "2026-07-01", all_day: true, title: "Trip", kind: "personal" };
  assert.deepEqual(pastIndexes([trip], NOW), []);
});

test("pastIndexes: holiday / observance / info items never roll off", () => {
  const items = [
    { start: "2026-07-01", all_day: true, title: "H", kind: "holiday" },
    { start: "2026-07-01", all_day: true, title: "O", kind: "observance" },
    { start: "2026-07-01", all_day: true, title: "I", kind: "info" },
  ];
  assert.deepEqual(pastIndexes(items, NOW), []);
});

test("pastIndexes: an event with no end is an instant — past once start passes", () => {
  const past = { start: "2026-07-01T13:00:00-04:00", all_day: false, title: "e", kind: "personal" };
  const upcoming = { start: "2026-07-01T15:00:00-04:00", all_day: false, title: "e", kind: "personal" };
  assert.deepEqual(pastIndexes([past], NOW), [0]);
  assert.deepEqual(pastIndexes([upcoming], NOW), []);
});

test("pastIndexes: disjoint from nextUp — the emphasized event can never roll off", () => {
  // The two scans partition today's timed events around the same "now": nextUp
  // picks the first NOT-past one, pastIndexes collects the past ones.
  const items = [timed(9, 10), timed(13, 15), timed(16, 17)];
  const past = pastIndexes(items, NOW);
  assert.deepEqual(past, [0]);
  assert.equal(past.includes(nextUp(items, NOW)), false);
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

// ── fmtHiLo (hero's stacked H/L pair beside the big temp) ─────────────────────

test("fmtHiLo: glyph + degree string per line, hi over lo", () => {
  assert.deepEqual(fmtHiLo({ high_f: 75, low_f: 61 }), {
    hi: { glyph: "▴", temp: "75°" },
    lo: { glyph: "▾", temp: "61°" },
  });
});

test("fmtHiLo: negative temps keep the sign on the value", () => {
  assert.deepEqual(fmtHiLo({ high_f: 10, low_f: -5 }), {
    hi: { glyph: "▴", temp: "10°" },
    lo: { glyph: "▾", temp: "-5°" },
  });
});

// ── planDayFit (pure half of fitDayInPlace: roll-off then bottom trim) ────────
// Heights are arbitrary px; the shell feeds real measurements. lineHeight = 10
// throughout so the summary-line charge is visible in the arithmetic.

test("planDayFit: a fitting row is a no-op plan", () => {
  assert.deepEqual(planDayFit(100, [30, 30, 30], [false, false, false], 10, 100), {
    hide: [],
    earlierCount: 0,
    moreCount: 0,
  });
});

test("planDayFit: no children -> no-op even when over budget (nothing to trim)", () => {
  assert.deepEqual(planDayFit(120, [], [], 10, 100), {
    hide: [],
    earlierCount: 0,
    moreCount: 0,
  });
});

test("planDayFit: no past rows -> bottom-up trim into '+N more'", () => {
  // 130 over an 80 budget: +10 for the more line -> must shed 60 -> the last
  // two 30px rows go, oldest content at the top survives.
  const plan = planDayFit(130, [30, 30, 30], [false, false, false], 10, 80);
  assert.deepEqual(plan, { hide: [1, 2], earlierCount: 0, moreCount: 2 });
});

test("planDayFit: past rows roll off FIRST, oldest first, into '+N earlier'", () => {
  // Row 0 is a pill (not past), rows 1-2 are past, row 3 upcoming. 140 over a
  // 120 budget: +10 earlier line -> shed 30 -> rolling row 1 (30px) fits it.
  // The upcoming row 3 is untouched — that's the point of roll-off.
  const plan = planDayFit(140, [20, 30, 30, 30], [false, true, true, false], 10, 120);
  assert.deepEqual(plan, { hide: [1], earlierCount: 1, moreCount: 0 });
});

test("planDayFit: the earlier line's own height is charged before deciding", () => {
  // 125 over a 120 budget: without the +10 line one 30px roll-off would leave
  // 95 ≤ 120 — but the line makes it 135, still requiring only one roll
  // (135-30=105). Budget 101 instead: one roll -> 105 > 101 -> a second rolls.
  const plan = planDayFit(125, [20, 30, 30, 30], [false, true, true, false], 10, 101);
  assert.deepEqual(plan, { hide: [1, 2], earlierCount: 2, moreCount: 0 });
});

test("planDayFit: roll-off exhausted -> trim resumes from the bottom", () => {
  // Both past rows roll (+10 line, shed 60 -> 150 -> still over 80), then the
  // +N more line (+10) and the bottom row must go too.
  const plan = planDayFit(200, [20, 30, 30, 40], [false, true, true, false], 10, 80);
  assert.deepEqual(plan, { hide: [1, 2, 3], earlierCount: 2, moreCount: 1 });
});

test("planDayFit: bottom trim never reaches above the '+N earlier' line", () => {
  // Everything below the first past row is gone and it STILL overflows — the
  // pill at index 0 (above the earlier line) is protected regardless.
  const plan = planDayFit(500, [20, 30, 30, 40], [false, true, true, false], 10, 50);
  assert.deepEqual(plan, { hide: [1, 2, 3], earlierCount: 2, moreCount: 1 });
});

test("planDayFit: without roll-off the trim may take every child", () => {
  const plan = planDayFit(500, [30, 30, 30], [false, false, false], 10, 50);
  assert.deepEqual(plan, { hide: [0, 1, 2], earlierCount: 0, moreCount: 3 });
});

test("planDayFit: hide indexes are ascending regardless of trim order", () => {
  // Roll-off pushes 1 then 2; the bottom trim pushes 3 — sorted output so the
  // shell can remove by index without caring about phase order.
  const plan = planDayFit(500, [20, 30, 30, 40], [false, true, true, false], 10, 50);
  assert.deepEqual(plan.hide, [...plan.hide].sort((a, b) => a - b));
});

// ── planColumnFit (pure half of fitColumnInPlace: drop later days) ────────────

test("planColumnFit: a fitting column is a no-op (footer probe can't push it over)", () => {
  // The old in-place code appended the probe footer BEFORE checking fit, so an
  // exactly-fitting column could lose its last day. The planner returns no-op.
  assert.deepEqual(planColumnFit(100, [50, 50], 10, 100), {
    dropCount: 0,
    showFooter: false,
  });
});

test("planColumnFit: a single day-row is never dropped", () => {
  assert.deepEqual(planColumnFit(200, [200], 10, 100), {
    dropCount: 0,
    showFooter: false,
  });
});

test("planColumnFit: drops days from the END until the column + footer fit", () => {
  // 180 over a 120 budget: +10 footer -> 190 -> both 40px later days drop
  // (190 -> 150, still over -> 110), leaving the footer room to show.
  assert.deepEqual(planColumnFit(180, [100, 40, 40], 10, 120), {
    dropCount: 2,
    showFooter: true,
  });
});

test("planColumnFit: the first day is protected even when it alone overflows", () => {
  // Dropping every later day still leaves 200+10 over 100 — the footer is
  // omitted (the first day's own '+N more' signals truncation instead).
  assert.deepEqual(planColumnFit(280, [200, 40, 40], 10, 100), {
    dropCount: 2,
    showFooter: false,
  });
});

test("planColumnFit: the footer's own height is charged before deciding", () => {
  // 145 over a 125 budget with a 20px footer: a planner that ignored the
  // footer would stop after one drop (145 - 20 = 125 ≤ 125) and the labeled
  // footer would overflow; charging it up front (165) forces the second drop
  // (165 -> 145 -> 125 ≤ 125).
  assert.deepEqual(planColumnFit(145, [85, 20, 20, 20], 20, 125), {
    dropCount: 2,
    showFooter: true,
  });
});

// mock.timers auto-reset per test via t.mock, but reset the top-level mock too in
// case any test used it directly.
test.after(() => mock.timers.reset());
