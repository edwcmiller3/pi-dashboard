// Pure agenda transforms and fit planners. A layout measures pixel heights and
// applies the returned plan. Heights compose linearly because the containers are
// no-gap flex columns, so the planners simulate removals instead of re-measuring.

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

// Today (the first group) gets column 1 to itself; later days stack in column 2.
// A deliberate hierarchy, not height-balancing.
/** @param {DayGroup[]} groups @returns {[DayGroup[], DayGroup[]]} */
export function splitColumns(groups) {
  if (groups.length < 2) return [groups, []];
  return [groups.slice(0, 1), groups.slice(1)];
}

// An event-less today has no group; synthesize an empty one so column 1 shows
// "Nothing today" rather than silently showing a future day.
/** @param {DayGroup[]} groups @param {string} todayKey @returns {DayGroup[]} */
export function withTodayGroup(groups, todayKey) {
  if (groups.length > 0 && groups[0].date === todayKey) return groups;
  return [{ date: todayKey, items: [] }, ...groups];
}

// "Nothing today" means no personal commitments; a holiday pill may still show.
/** @param {AgendaItem[]} items @returns {boolean} */
export function hasPersonalEvents(items) {
  return items.some((i) => i.kind === "personal");
}

// Index of the first not-yet-ended timed personal event, or -1. "Past" keys off
// END, so a long meeting stays highlighted until it truly ends.
/** @param {AgendaItem[]} items @param {Date} now @returns {number} */
export function nextUp(items, now) {
  for (let i = 0; i < items.length; i++) {
    const ev = items[i];
    if (ev.kind !== "personal" || ev.all_day) continue;
    if (now < localInstant(ev.end ?? ev.start)) return i;
  }
  return -1;
}

// Roll-off candidates: the exact complement of nextUp's filter, so the
// emphasized event is never one. Whether any hide is planDayFit's call.
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

// Past rows hide first (oldest first) into "+N earlier"; only then does the
// bottom "+N more" trim start. Summary-line height is charged before deciding,
// so a label can't push the row back over budget.
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

// Later days drop from the end; day 0 is never dropped (its events are trimmed
// via planDayFit instead). Footer height is charged up front so it can't overflow.
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
