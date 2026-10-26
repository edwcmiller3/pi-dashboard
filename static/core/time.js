// Pure time helpers. Event/sunrise/sunset times render the wall-clock encoded in
// each ISO string (the API's offset), never re-zoned to the Pi clock; only the big
// clock ticks live from the browser.

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

// "2026-06-28T08:30:00-04:00" -> {date, time:{hh,mm}}, no re-zoning;
// date-only "2026-07-04" -> {date, time:null}.
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

// A date-only stamp here is contract drift; render "—" rather than crash.
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

// Same shape as the date half of an event's local `start`, so they compare directly.
/** @param {Date} [d] @returns {string} */
export function localDayKey(d = new Date()) {
  return `${d.getFullYear()}-${pad2(d.getMonth() + 1)}-${pad2(d.getDate())}`;
}

// `prevDay` is null on first run, which is not a rollover.
/** @param {string | null} prevDay @param {string} nowDay @returns {boolean} */
export function dayRolledOver(prevDay, nowDay) {
  return prevDay !== null && nowDay !== prevDay;
}

// The ISO string's wall-clock parts as a local Date, no re-zoning:
// "2026-07-01T14:00:00-04:00" -> local 14:00; date-only -> local midnight.
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
