// Core agenda transforms + pure fit planners - DOM-free and unit-testable.
//
// The transforms group/split the event list the way the two-column agenda
// renders; the planners are the measure-and-fit algorithm factored out of the
// DOM. A layout's fit SHELL measures real pixel heights and applies the returned
// plan; everything decision-shaped lives here. Heights compose linearly because
// the containers are no-gap flex columns: removing a child shrinks the container
// by exactly that child's measured height, so the planners can simulate removals
// instead of re-measuring.

import { localParts, localInstant } from "./time.js";

/** @typedef {import("./contract.js").AgendaItem} AgendaItem */

/**
 * A day's events, grouped for the agenda columns.
 * @typedef {object} DayGroup
 * @property {string} date "YYYY-MM-DD"
 * @property {AgendaItem[]} items
 */

// Flat, pre-sorted event list -> ordered [{date, items}] grouped by local day.
/** @param {AgendaItem[]} events @returns {DayGroup[]} */
export function groupByDay(events) {
  const map = new Map();
  for (const ev of events) {
    const { date } = localParts(ev.start);
    if (!map.has(date)) map.set(date, []);
    map.get(date).push(ev);
  }
  return [...map.entries()].map(([date, items]) => ({ date, items }));
}

// Split ordered day groups into two columns the way the README mockup does:
// TODAY (the first/earliest group - events arrive pre-sorted) gets column 1 to
// itself; all upcoming days stack in column 2, chronological order preserved.
// A deliberate hierarchy (today is the focus), NOT height-balancing.
// Edge: < 2 groups -> everything in col 1, col 2 empty.
/** @param {DayGroup[]} groups @returns {[DayGroup[], DayGroup[]]} */
export function splitColumns(groups) {
  if (groups.length < 2) return [groups, []];
  return [groups.slice(0, 1), groups.slice(1)];
}

// Guarantee today's group leads the agenda so column 1 always represents today.
// Events arrive pre-sorted and windowed from today forward, so today - if it has
// any events (personal, holiday, or marker) - is already `groups[0]`. When today
// has NO events no group exists, so synthesize an empty one: this is what lets
// the quiet-day "Nothing today" state render instead of column 1 silently
// showing a future day. `todayKey` is a localDayKey ("YYYY-MM-DD"). Pure.
/** @param {DayGroup[]} groups @param {string} todayKey @returns {DayGroup[]} */
export function withTodayGroup(groups, todayKey) {
  if (groups.length > 0 && groups[0].date === todayKey) return groups;
  return [{ date: todayKey, items: [] }, ...groups];
}

// Whether a day's items include a personal (Proton) event, as opposed to only
// holidays/observances/DST markers. Drives the quiet-day state: "Nothing today"
// means no personal commitments - a holiday pill may still sit above it. Pure.
/** @param {AgendaItem[]} items @returns {boolean} */
export function hasPersonalEvents(items) {
  return items.some((i) => i.kind === "personal");
}

// The index of the day's event to emphasize as "next up", or -1 for none.
// Considers TIMED personal events only - all-day / holiday / marker items are
// day context, never "next". The target is the earliest such event that isn't
// already past: an in-progress one (start ≤ now < end) if any exists, else the
// soonest upcoming (now < start). Items arrive pre-sorted by start, so the first
// not-past one IS the earliest. "Past" keys off the event's END (the half-open
// [start, end) contract; end absent -> an instant at start), so a long meeting
// stays highlighted until it truly ends, not just until the next event starts.
// Pure.
/** @param {AgendaItem[]} items @param {Date} now @returns {number} */
export function nextUp(items, now) {
  for (let i = 0; i < items.length; i++) {
    const ev = items[i];
    if (ev.kind !== "personal" || ev.all_day) continue;
    if (now < localInstant(ev.end ?? ev.start)) return i;
  }
  return -1;
}

// The indices of the day's events that MAY roll off when today overflows the
// fit budget: already-past TIMED PERSONAL events - the complement of nextUp's
// "not past" test (now < end, half-open [start, end); end absent -> an instant
// at start), over the same kind/all_day filter, so the emphasized event can
// never be a candidate. All-day and holiday/observance/info items are day
// context and never roll off. Ascending = oldest first - the order the fit
// pass hides them in. This is a candidate list, not a command: whether any
// actually hide is the fit pass's call (demand-driven - only on overflow, only
// as many as needed). Pure.
/** @param {AgendaItem[]} items @param {Date} now @returns {number[]} */
export function pastIndexes(items, now) {
  return items.flatMap((ev, i) =>
    ev.kind === "personal" && !ev.all_day && !(now < localInstant(ev.end ?? ev.start)) ? [i] : [],
  );
}

/**
 * The fit plan for one day-row.
 * @typedef {object} DayFitPlan
 * @property {number[]} hide child indexes to remove, ascending
 * @property {number} earlierCount past rows rolled off (>0 -> insert a
 *   "+N earlier" line where the FIRST past child sat)
 * @property {number} moreCount rows trimmed off the bottom (>0 -> append a
 *   "+N more" line)
 */

// Plan how to fit a day-row into `budget` px. Mirrors the roll-off contract
// documented on fitDayInPlace: already-past rows hide FIRST (oldest first) into
// a "+N earlier" line; only when every past row is gone and the row still
// overflows does the bottom "+N more" trim resume - and that trim never reaches
// above the "+N earlier" line (the pills before it are protected). The summary
// lines' own height (`lineHeight`) is charged BEFORE deciding, so a final label
// can't push the row back over budget. Demand-driven: a fitting row is a no-op
// plan. Pure.
/**
 * @param {number} totalHeight measured px of the whole day-row
 * @param {number[]} childHeights per-child measured px, in DOM order
 * @param {boolean[]} isPast per-child roll-off candidacy (`.is-past`), in DOM order
 * @param {number} lineHeight px one "+N …" summary line occupies
 * @param {number} budget
 * @returns {DayFitPlan}
 */
export function planDayFit(totalHeight, childHeights, isPast, lineHeight, budget) {
  /** @type {number[]} */
  const hide = [];
  if (totalHeight <= budget || childHeights.length === 0) {
    return { hide, earlierCount: 0, moreCount: 0 };
  }
  let h = totalHeight;
  let earlierCount = 0;
  const past = childHeights.map((_, i) => i).filter((i) => isPast[i]);
  if (past.length > 0) {
    h += lineHeight; // the "+N earlier" line takes the oldest past row's place
    for (const i of past) {
      if (h <= budget) break;
      hide.push(i);
      h -= childHeights[i];
      earlierCount += 1;
    }
    if (h <= budget) return { hide, earlierCount, moreCount: 0 };
  }
  h += lineHeight; // the "+N more" line
  let moreCount = 0;
  const hidden = new Set(hide);
  // With a roll-off summary in place, the bottom-up trim stops at it - children
  // before the first past row (the all-day/holiday pills) never trim.
  const floor = earlierCount > 0 ? past[0] : 0;
  for (let i = childHeights.length - 1; i >= floor && h > budget; i--) {
    if (hidden.has(i)) continue;
    hide.push(i);
    h -= childHeights[i];
    moreCount += 1;
  }
  return { hide: [...hide].sort((a, b) => a - b), earlierCount, moreCount };
}

/**
 * The fit plan for a column of day-rows.
 * @typedef {object} ColumnFitPlan
 * @property {number} dropCount day-rows to remove from the END of the column
 * @property {boolean} showFooter append the "+N more days" footer (only when it
 *   itself fits - otherwise the protected day's own "+N more" already signals
 *   truncation)
 */

// Plan how to fit a column into `budget` px: later days drop from the end; the
// first day is protected (index 0 is never dropped - the shell trims its EVENTS
// via planDayFit instead). The footer's height is charged up front so labeling
// it can't overflow; a column that already fits is a no-op (the old in-place
// code could drop a day from an exactly-fitting column because its probe footer
// momentarily pushed it over). Pure.
/**
 * @param {number} totalHeight measured px of the whole column
 * @param {number[]} dayHeights per-day-row measured px, in DOM order
 * @param {number} footerHeight px the "+N more days" footer occupies
 * @param {number} budget
 * @returns {ColumnFitPlan}
 */
export function planColumnFit(totalHeight, dayHeights, footerHeight, budget) {
  if (totalHeight <= budget || dayHeights.length < 2) {
    return { dropCount: 0, showFooter: false };
  }
  let h = totalHeight + footerHeight;
  let dropCount = 0;
  for (let i = dayHeights.length - 1; i >= 1 && h > budget; i--) {
    h -= dayHeights[i];
    dropCount += 1;
  }
  return { dropCount, showFooter: dropCount > 0 && h <= budget };
}
