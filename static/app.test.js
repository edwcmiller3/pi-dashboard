// Unit tests for the pure JS transforms in app.js.
// Run with Node's built-in runner (no deps):  node --test  (from static/)
//
// app.js is an ES module whose bootstrap is guarded by `typeof document`, so
// importing it here runs no DOM/init side effects — only the pure exports load.

import test from "node:test";
import assert from "node:assert/strict";

import {
  localParts,
  to12,
  fmtCompact,
  fmtLong,
  localDate,
  isSameDay,
  groupByDay,
  splitColumns,
  dayLabel,
  pickUpdated,
} from "./app.js";

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

// ── groupByDay (preserves input order of first appearance) ───────────────────

test("groupByDay: groups by local date, preserving encounter order", () => {
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

test("groupByDay: empty -> empty", () => {
  assert.deepEqual(groupByDay([]), []);
});

// ── splitColumns ─────────────────────────────────────────────────────────────

const g = (date, n) => ({ date, items: Array.from({ length: n }, (_, i) => i) });

test("splitColumns: 0 groups -> both empty", () => {
  assert.deepEqual(splitColumns([]), [[], []]);
});

test("splitColumns: 1 group -> all in col1, col2 empty", () => {
  const groups = [g("d1", 3)];
  assert.deepEqual(splitColumns(groups), [groups, []]);
});

test("splitColumns: 2 groups -> today (first) alone in col1, rest in col2", () => {
  const groups = [g("d1", 2), g("d2", 2)];
  const [c1, c2] = splitColumns(groups);
  assert.equal(c1.length, 1);
  assert.equal(c2.length, 1);
  assert.equal(c1[0].date, "d1");
  assert.equal(c2[0].date, "d2");
});

test("splitColumns: a light today still gets col1 to itself (no balancing)", () => {
  // The old height-balanced rule would pull d2 up beside a light d1; the v4
  // rule keeps today alone regardless of how few events it has.
  const groups = [g("d1", 1), g("d2", 100)];
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
  const groups = [g("d1", 1), g("d2", 1), g("d3", 1), g("d4", 1)];
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
  const groups = [g("d1", 1), g("d2", 1), g("d3", 1)];
  const before = groups.map((x) => x.date);
  splitColumns(groups);
  assert.deepEqual(
    groups.map((x) => x.date),
    before,
  );
});

// ── dayLabel ─────────────────────────────────────────────────────────────────

test("dayLabel: today -> isToday + 'Today'", () => {
  const now = new Date();
  const iso = `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, "0")}-${String(
    now.getDate(),
  ).padStart(2, "0")}`;
  const label = dayLabel(iso);
  assert.equal(label.isToday, true);
  assert.equal(label.dname, "Today");
});

test("dayLabel: a non-today date -> isToday false, weekday name (not 'Today')", () => {
  // Pick a date guaranteed not to be today.
  const future = dayLabel("2099-01-02"); // a Friday
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
