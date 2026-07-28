// Core time helpers - pure, DOM-free, unit-testable without a browser.
//
// Time policy: event/sunrise/sunset times are rendered from the wall-clock
// encoded in each ISO string's local part (render from the API offset, not the
// Pi clock). The big clock is the deliberate exception - it ticks live from the
// browser (see the layout's renderClock hook).

/**
 * A parsed local wall-clock time (no zone).
 * @typedef {object} LocalTime
 * @property {number} hh
 * @property {number} mm
 */

/**
 * @typedef {object} LocalParts
 * @property {string} date "YYYY-MM-DD"
 * @property {LocalTime | null} time null for a date-only string
 */

// Split an ISO string into its date and (optional) local wall-clock time,
// WITHOUT re-zoning. "2026-06-28T08:30:00-04:00" -> {date, time:{hh,mm}};
// a date-only "2026-07-04" -> {date, time:null}.
/**
 * @param {string} iso
 * @returns {LocalParts}
 */
export function localParts(iso) {
  const t = iso.indexOf("T");
  if (t === -1) return { date: iso, time: null };
  return {
    date: iso.slice(0, t),
    time: { hh: +iso.slice(t + 1, t + 3), mm: +iso.slice(t + 4, t + 6) },
  };
}

/**
 * @param {number} hh 0–23
 * @returns {{ h: number, ampm: "AM" | "PM" }}
 */
export function to12(hh) {
  const ampm = hh >= 12 ? "PM" : "AM";
  const h = hh % 12 || 12;
  return { h, ampm };
}

/** @param {number} n @returns {string} */
export const pad2 = (n) => String(n).padStart(2, "0");

// "8:30a" / "12:00p" - compact, for events and sunrise/sunset.
/** @param {LocalTime} time @returns {string} */
export function fmtCompact({ hh, mm }) {
  const { h, ampm } = to12(hh);
  return `${h}:${pad2(mm)}${ampm[0].toLowerCase()}`;
}

// Compact time, or an em-dash when the time is null - a date-only ISO string is
// contract drift for sunrise/sunset/updated stamps, so render "—" rather than crash.
/** @param {LocalTime | null} time @returns {string} */
export const fmtCompactOr = (time) => (time ? fmtCompact(time) : "—");

// "9:40 AM" - for the status "Updated" stamp.
/** @param {LocalTime} time @returns {string} */
export function fmtLong({ hh, mm }) {
  const { h, ampm } = to12(hh);
  return `${h}:${pad2(mm)} ${ampm}`;
}

// Parse a date-only "YYYY-MM-DD" as a LOCAL calendar date (no UTC shift).
/** @param {string} dateStr @returns {Date} */
export function localDate(dateStr) {
  const [y, m, d] = dateStr.split("-").map(Number);
  return new Date(y, m - 1, d);
}

/** @param {Date} a @param {Date} b @returns {boolean} */
export function isSameDay(a, b) {
  return (
    a.getFullYear() === b.getFullYear() &&
    a.getMonth() === b.getMonth() &&
    a.getDate() === b.getDate()
  );
}

// Local calendar day as "YYYY-MM-DD" - the date half of an event's local `start`,
// so it compares directly. Used to detect the midnight rollover.
/** @param {Date} [d] @returns {string} */
export function localDayKey(d = new Date()) {
  return `${d.getFullYear()}-${pad2(d.getMonth() + 1)}-${pad2(d.getDate())}`;
}

// Whether the local calendar day has changed since `prevDay` (a localDayKey, or
// null on first run). At midnight this flips, driving a data reload so the agenda
// re-groups - "Today" moves to the new day and a holiday/event entering the
// window appears - instead of waiting for the next 15-min poll.
/** @param {string | null} prevDay @param {string} nowDay @returns {boolean} */
export function dayRolledOver(prevDay, nowDay) {
  return prevDay !== null && nowDay !== prevDay;
}

// A Date in the browser's LOCAL zone built from an ISO string's encoded
// wall-clock parts (date + optional time), WITHOUT re-zoning - the same "render
// the local part, don't reinterpret the offset" policy the event times use. So
// "2026-07-01T14:00:00-04:00" -> local 14:00 on 2026-07-01; a date-only string
// -> local midnight. Used to compare event times against "now". Pure.
/** @param {string} iso @returns {Date} */
export function localInstant(iso) {
  const { date, time } = localParts(iso);
  const d = localDate(date);
  if (time) d.setHours(time.hh, time.mm, 0, 0);
  return d;
}

/**
 * @param {string} dateStr "YYYY-MM-DD"
 * @returns {{ isToday: boolean, dname: string, ddate: string }}
 */
export function dayLabel(dateStr) {
  const dt = localDate(dateStr);
  const isToday = isSameDay(dt, new Date());
  return {
    isToday,
    dname: isToday ? "Today" : dt.toLocaleDateString(undefined, { weekday: "long" }),
    ddate: dt.toLocaleDateString(undefined, { month: "short", day: "numeric" }),
  };
}
