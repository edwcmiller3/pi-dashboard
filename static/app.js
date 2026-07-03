// Pi Dashboard front-end — vanilla, functional render of the data contract.
//
// Phase 3: reads the live JSON API (/api/data), which the backend refresh loop
// keeps warm. Every render function consumes the same contract the Phase-2 fake
// data was authored against, so the swap was just this DATA_URL + a poll cycle.
//
// Time policy: event/sunrise/sunset times are rendered from the wall-clock
// encoded in each ISO string's local part (honoring "render from the API
// offset, not the Pi clock"). The big clock is the deliberate exception — it
// ticks live from the browser (clock-sync honesty is a Phase-6 concern).

// ── contract types (mirror app/contract.py) ─────────────────────────────────
// JSDoc typedefs so an editor and `tsc --checkJs` verify the contract the
// backend produces is consumed correctly here — the Python side builds a precise
// DashboardDoc, and this recovers most of that safety on the consumer with no
// build step (these are comments). Keep in sync with app/contract.py.

/** @typedef {"personal" | "holiday" | "observance" | "info"} Kind */

/**
 * @typedef {object} AgendaItem
 * @property {string} start ISO datetime-with-offset (timed) or "YYYY-MM-DD" (all-day)
 * @property {string} [end] exclusive upper bound; absent on single-day/instant items
 * @property {boolean} all_day
 * @property {string} title untrusted PII — render via textContent only
 * @property {Kind} kind
 */

/**
 * @typedef {object} CurrentWeather
 * @property {number} temp_f
 * @property {number} feels_like_f
 * @property {number} code
 * @property {string} text human label
 * @property {string} icon a weather-icons class ("wi-*")
 * @property {boolean} is_day
 * @property {number} humidity_pct
 * @property {number} wind_mph
 * @property {number} precip_prob_pct
 * @property {number} high_f
 * @property {number} low_f
 * @property {string} sunrise ISO datetime-with-offset
 * @property {string} sunset ISO datetime-with-offset
 */

/**
 * @typedef {object} ForecastDay
 * @property {string} date
 * @property {number} code
 * @property {string} text
 * @property {string} icon a weather-icons class ("wi-*")
 * @property {number} high_f
 * @property {number} low_f
 * @property {number} precip_prob_pct
 * @property {boolean} [precip_expected] backend is_wet(code) gate; absent (a
 *   pre-field cached block) reads as dry, so the precip line stays hidden
 */

/**
 * @typedef {object} WeatherBlock
 * @property {boolean} ok
 * @property {string | null} fetched_at
 * @property {number} [ttl]
 * @property {string} [attempted_at]
 * @property {CurrentWeather} current
 * @property {ForecastDay[]} forecast
 */

/**
 * @typedef {object} CalendarBlock
 * @property {boolean} ok
 * @property {string | null} fetched_at
 * @property {number} [ttl]
 * @property {string} [attempted_at]
 * @property {AgendaItem[]} events
 */

/**
 * @typedef {object} DashboardDoc
 * @property {string} generated_at
 * @property {boolean} clock_synced
 * @property {WeatherBlock} weather
 * @property {CalendarBlock} calendar
 */

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

/**
 * A day's events, grouped for the agenda columns.
 * @typedef {object} DayGroup
 * @property {string} date "YYYY-MM-DD"
 * @property {AgendaItem[]} items
 */

const DATA_URL = "/api/data";

// How often the page re-fetches the API. Phase 6 makes refresh TTL-aware; for
// now a fixed poll matching the backend's fetch cadence is plenty.
const POLL_INTERVAL_MS = 15 * 60 * 1000;

// After a FAILED load, retry soon rather than waiting the full poll — so the
// cold-boot 503 window (cache not yet warm) and transient blips clear in
// seconds, not up to 15 minutes.
const RETRY_INTERVAL_MS = 30 * 1000;

// ── pure time helpers ───────────────────────────────────────────────────────

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
const pad2 = (n) => String(n).padStart(2, "0");

// "8:30a" / "12:00p" — compact, for events and sunrise/sunset.
/** @param {LocalTime} time @returns {string} */
export function fmtCompact({ hh, mm }) {
  const { h, ampm } = to12(hh);
  return `${h}:${pad2(mm)}${ampm[0].toLowerCase()}`;
}

// "9:40 AM" — for the status "Updated" stamp.
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

// Local calendar day as "YYYY-MM-DD" — the date half of an event's local `start`,
// so it compares directly. Used to detect the midnight rollover.
/** @param {Date} [d] @returns {string} */
export function localDayKey(d = new Date()) {
  return `${d.getFullYear()}-${pad2(d.getMonth() + 1)}-${pad2(d.getDate())}`;
}

// Whether the local calendar day has changed since `prevDay` (a localDayKey, or
// null on first run). At midnight this flips, driving a data reload so the agenda
// re-groups — "Today" moves to the new day and a holiday/event entering the
// window appears — instead of waiting for the next 15-min poll.
/** @param {string | null} prevDay @param {string} nowDay @returns {boolean} */
export function dayRolledOver(prevDay, nowDay) {
  return prevDay !== null && nowDay !== prevDay;
}

// ── nightly blackout (wall-clock-driven) ─────────────────────────────────────

// The 1a–6a blackout window. Spikes 0.4/0.5 found this panel has no DDC/CI and
// no /sys/class/backlight, so there is NO hardware brightness/power channel —
// and cutting the HDMI signal (wlopm) can't hold it dark either (the panel drops
// hotplug-detect, the Pi re-detects, ~2s later it's back on). The only blackout
// left is this full-screen CSS-black overlay: backlight + Pi stay on, the screen
// just renders black. It is driven by the wall clock (time-of-day), NOT a
// runtime timer, on purpose: the Phase-8 nightly 03:00 reboot lands INSIDE this
// window, so a fresh page load mid-window must return to black — a timer
// counting from boot would instead paint the bright dashboard.
const BLACKOUT_START_HOUR = 1; // inclusive — 01:00 local
const BLACKOUT_END_HOUR = 6; // exclusive — 06:00 local

// Whether `date`'s local hour falls in the blackout window. Pure. Hour-grained
// (the window edges are whole hours), so the overlay flips exactly at the top of
// 01:00 and 06:00. Supports a window that wraps past midnight (start > end),
// though the shipped 1a–6a window does not.
/**
 * @param {Date} date
 * @param {number} [startHour]
 * @param {number} [endHour]
 * @returns {boolean}
 */
export function inBlackout(date, startHour = BLACKOUT_START_HOUR, endHour = BLACKOUT_END_HOUR) {
  if (startHour === endHour) return false;
  const h = date.getHours();
  return startHour < endHour ? h >= startHour && h < endHour : h >= startHour || h < endHour;
}

// ── pure agenda transforms ───────────────────────────────────────────────────

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

// Split ordered day groups into two columns the way the v4 mockup does:
// TODAY (the first/earliest group — events arrive pre-sorted) gets column 1 to
// itself; all upcoming days stack in column 2, chronological order preserved.
// This is a deliberate hierarchy (today is the focus), NOT height-balancing.
// Edge: < 2 groups -> everything in col 1, col 2 empty.
/** @param {DayGroup[]} groups @returns {[DayGroup[], DayGroup[]]} */
export function splitColumns(groups) {
  if (groups.length < 2) return [groups, []];
  return [groups.slice(0, 1), groups.slice(1)];
}

// Guarantee today's group leads the agenda so column 1 always represents today.
// Events arrive pre-sorted and windowed from today forward, so today — if it has
// any events (personal, holiday, or marker) — is already `groups[0]`. When today
// has NO events, no group exists for it, so synthesize an empty one: this is what
// lets the quiet-day "Nothing today" state render instead of column 1 silently
// showing a future day. `todayKey` is a localDayKey ("YYYY-MM-DD"). Pure.
/** @param {DayGroup[]} groups @param {string} todayKey @returns {DayGroup[]} */
export function withTodayGroup(groups, todayKey) {
  if (groups.length > 0 && groups[0].date === todayKey) return groups;
  return [{ date: todayKey, items: [] }, ...groups];
}

// Whether a day's items include a personal (Proton) event, as opposed to only
// holidays/observances/DST markers. Drives the quiet-day state: "Nothing today"
// means no personal commitments — a holiday pill may still sit above it. Pure.
/** @param {AgendaItem[]} items @returns {boolean} */
export function hasPersonalEvents(items) {
  return items.some((i) => i.kind === "personal");
}

// A Date in the browser's LOCAL zone built from an ISO string's encoded
// wall-clock parts (date + optional time), WITHOUT re-zoning — the same "render
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

// The index of the day's event to emphasize as "next up", or -1 for none.
// Considers TIMED personal events only — all-day / holiday / marker items are
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
// fit budget: already-past TIMED PERSONAL events — the complement of nextUp's
// "not past" test (now < end, half-open [start, end); end absent -> an instant
// at start), over the same kind/all_day filter, so the emphasized event can
// never be a candidate. All-day and holiday/observance/info items are day
// context and never roll off. Ascending = oldest first — the order the fit
// pass hides them in. This is a candidate list, not a command: whether any
// actually hide is the fit pass's call (demand-driven — only on overflow, only
// as many as needed). Pure.
/** @param {AgendaItem[]} items @param {Date} now @returns {number[]} */
export function pastIndexes(items, now) {
  return items.flatMap((ev, i) =>
    ev.kind === "personal" && !ev.all_day && !(now < localInstant(ev.end ?? ev.start)) ? [i] : [],
  );
}

// "Updated" = the OLDEST fetched_at among sources that fetched OK — so the
// stamp honestly means "every fresh source is at least this current," never
// over-claiming by showing the most-recent one. Compared by instant (epoch) so
// mixed UTC offsets order correctly. Returns the chosen ISO string, or null
// when nothing fetched OK.
/**
 * @param {(WeatherBlock | CalendarBlock | null | undefined)[]} sources
 * @returns {string | null}
 */
export function pickUpdated(sources) {
  const stamps = sources
    .filter((s) => s && s.ok && s.fetched_at)
    .map((s) => s.fetched_at)
    // Drop unparseable stamps up front: Date.parse(bad) is NaN, and every `<`
    // comparison with NaN is false, so a garbage stamp encountered first would
    // "win" the min and never be beaten — over-claiming freshness. Filtering
    // makes the pick correct regardless of input order.
    .filter((iso) => !Number.isNaN(Date.parse(iso)));
  return stamps.reduce(
    (best, iso) => (best === null || Date.parse(iso) < Date.parse(best) ? iso : best),
    null,
  );
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

// ── inline SVG (refresh), matching the v4 mockup ─────────────────────────────

const REFRESH_SVG =
  '<svg viewBox="0 0 24 24" aria-hidden="true" stroke-linecap="round" stroke-linejoin="round">' +
  '<path d="M21 12a9 9 0 1 1-2.64-6.36"/><path d="M21 3v4h-4"/></svg>';

// ── DOM builders ─────────────────────────────────────────────────────────────

/**
 * @param {string} tag
 * @param {string | null} [className]
 * @param {string} [text]
 * @returns {HTMLElement}
 */
function el(tag, className, text) {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text != null) node.textContent = text;
  return node;
}

// `isNext` marks the "next up" event with a subtle highlight; `isPast` tags an
// already-past event `.is-past` — no CSS of its own, purely a marker the
// fitDayInPlace roll-off pass consumes. Both apply only to a personal timed
// row — the only kind nextUp/pastIndexes ever select — so the holiday/marker
// branches ignore them.
/** @param {AgendaItem} ev @param {boolean} [isNext] @param {boolean} [isPast] @returns {HTMLElement} */
function eventNode(ev, isNext = false, isPast = false) {
  // Federal holiday / lesser observance -> identical pill above the day's
  // events (no tiered visual weight — official and unofficial render the same;
  // `kind` stays distinct in the data as provenance only).
  if (ev.kind === "holiday" || ev.kind === "observance") {
    return el("span", "holiday", ev.title); // title as text (textContent) — never HTML
  }
  // DST / informational marker -> plain muted line.
  if (ev.kind === "info") {
    return el("span", "marker", ev.title);
  }
  // Personal event -> time + title row; the next-up one gets a subtle highlight
  // so the event to look at reads at a glance (no chip — the tint is enough).
  const { time } = localParts(ev.start);
  const row = el("div", "event" + (isNext ? " is-next" : "") + (isPast ? " is-past" : ""));
  const when =
    ev.all_day || !time ? el("span", "etime allday", "All day") : el("span", "etime", fmtCompact(time));
  row.append(when, el("span", "etitle", ev.title)); // title as text (textContent) — never HTML
  return row;
}

/** @param {DayGroup} group @param {boolean} [calendarOk] @param {boolean} [clockSynced] @returns {HTMLElement} */
function dayRowNode(group, calendarOk = true, clockSynced = true) {
  const { isToday, dname, ddate } = dayLabel(group.date);
  const row = el("div", "day-row" + (isToday ? " is-today" : ""));
  const label = el("div", "day-label");
  label.append(el("span", "dname", dname), el("span", "ddate", ddate));
  const events = el("div", "day-events");
  // "Today awareness": both the next-up highlight and the roll-off candidates
  // key off "now" over the same partition of today's items, so they share one
  // gate — TODAY only, and only when the clock is trustworthy (an unsynced Pi
  // clock — no RTC, pre-NTP boot — would mis-pick both; the Phase-6
  // clock-honesty gate; undefined/true = fine) — and one `now`, so the
  // emphasized row can never simultaneously be a roll-off candidate.
  const aware = isToday && clockSynced !== false;
  const now = new Date();
  const nextIdx = aware ? nextUp(group.items, now) : -1;
  const pastIdx = new Set(aware ? pastIndexes(group.items, now) : []);
  group.items.forEach((ev, i) => events.append(eventNode(ev, i === nextIdx, pastIdx.has(i))));
  // Quiet-day state: today with no personal events gets a friendly "Nothing
  // today" (holidays/observances above still show as context). Only when the
  // calendar fetched OK — on a stale/failed calendar we don't know today's
  // events, so we don't claim emptiness (the stale status dot signals it).
  if (isToday && calendarOk && !hasPersonalEvents(group.items)) {
    events.append(el("div", "day-empty", "Nothing today"));
  }
  row.append(label, events);
  return row;
}

// ── region renderers ─────────────────────────────────────────────────────────

// Surface the Pi's clock-sync honesty: the big clock ticks from the browser, so
// if the Pi clock isn't NTP-synced yet (no RTC, pre-network boot) it's wrong.
// Warn only when the backend explicitly reports clock_synced === false; an
// absent/true value (older cache, dev host) hides it.
/** @param {boolean | undefined} synced @returns {void} */
function setClockWarning(synced) {
  const warn = document.getElementById("clock-warn");
  if (warn) warn.hidden = synced !== false;
}

// Live wall-clock from the browser (the one time source NOT taken from the API).
function renderClock() {
  const now = new Date();
  const { h, ampm } = to12(now.getHours());
  // h/minutes are own numbers; build via el()/textContent so no human/contract
  // text is ever interpolated into markup here.
  const clock = document.getElementById("clock");
  clock.replaceChildren(`${h}:${pad2(now.getMinutes())}`, el("span", "ampm", ampm));
  document.getElementById("date").textContent = now.toLocaleDateString(undefined, {
    weekday: "long",
    month: "long",
    day: "numeric",
  });
}

// Show/hide the full-screen blackout overlay for the current wall-clock time.
// Toggled every second alongside the clock, so it flips at the top of 01:00 /
// 06:00 and is already correct on a fresh load (e.g. after the 03:00 reboot).
/** @param {Date} [now] @returns {void} */
function renderBlackout(now = new Date()) {
  const overlay = document.getElementById("blackout");
  if (overlay) overlay.hidden = !inBlackout(now);
}

// A weather <i class="wi wi-…"> glyph. The icon class is an OWN value (resolved
// by our backend's WMO->wi-* table), so it is safe in an attribute; human text
// (conditions, future alert/location strings) must NOT be built this way.
/** @param {string} iconClass @param {string} [extra] @returns {HTMLElement} */
function wiIcon(iconClass, extra) {
  return el("i", "wi " + iconClass + (extra ? " " + extra : ""));
}

// A "stat" cell: an icon (optional) + uppercase key label + value. The label
// and value are set via textContent — never interpolated as HTML.
/**
 * @param {string | null} iconClass
 * @param {string} label
 * @param {string} value
 * @returns {HTMLElement}
 */
function statCell(iconClass, label, value) {
  const cell = el("div", "stat");
  const k = el("span", "k");
  if (iconClass) k.append(wiIcon(iconClass), " ");
  k.append(label);
  cell.append(k, el("span", "v", value));
  return cell;
}

/** @param {WeatherBlock} weather @returns {void} */
function renderCurrent(weather) {
  const c = weather.current;
  const card = document.getElementById("current-card");
  card.replaceChildren();

  const main = el("div", "cur-main");
  const temp = el("div", "cur-temp");
  temp.append(String(c.temp_f), el("span", "deg", "°"));
  const cond = el("div", "cur-cond");
  // c.text is HUMAN TEXT — route through textContent, never innerHTML.
  cond.append(
    c.text + " ",
    el("small", null, `· H ${c.high_f}° / L ${c.low_f}°`),
  );
  main.append(temp, cond);

  const stats = el("div", "cur-stats");
  stats.append(
    statCell(null, "Feels like", `${c.feels_like_f}°`),
    statCell("wi-raindrop", "Rain", `${c.precip_prob_pct}%`),
    statCell("wi-strong-wind", "Wind", `${c.wind_mph} mph`),
    statCell("wi-humidity", "Humidity", `${c.humidity_pct}%`),
    statCell("wi-sunrise", "Sunrise", fmtCompact(localParts(c.sunrise).time)),
    statCell("wi-sunset", "Sunset", fmtCompact(localParts(c.sunset).time)),
  );

  card.append(wiIcon(c.icon, "cur-icon"), main, el("div", "cur-div"), stats);
}

/** @param {ForecastDay[]} forecast @returns {void} */
function renderForecast(forecast) {
  const root = document.getElementById("forecast");
  root.replaceChildren();
  // The grid is a fixed repeat(4,1fr); slice defensively so a short/long feed
  // never misaligns it.
  for (const f of forecast.slice(0, 4)) {
    const dname = localDate(f.date).toLocaleDateString(undefined, { weekday: "long" });
    const card = el("section", "glass fcard");

    const temp = el("span", "ftemp");
    temp.append(`${f.high_f}°`, el("span", "lo", ` / ${f.low_f}°`));

    // Right of the icon: temps, with the precip-chance line beneath — shown only
    // on codes that precipitate (backend is_wet gate); an absent flag reads dry.
    const right = el("div", "fright");
    right.append(temp);
    if (f.precip_expected) {
      const precip = el("div", "fprecip");
      precip.append(wiIcon("wi-raindrop"), el("span", null, `${f.precip_prob_pct}%`));
      right.append(precip);
    }

    // Middle band: bigger icon on the left, temps/precip on the right, grouped
    // and centered as a unit (not edge-justified).
    const mid = el("div", "fmid");
    mid.append(wiIcon(f.icon, "fcard-icon"), right);

    // day (top) · icon+temps (middle) · condition text (bottom, mirrors the day).
    card.append(el("span", "fday", dname), mid, el("span", "fdesc", f.text));
    root.append(card);
  }
}

// Measured render height of a node (includes padding/wrapping — the real px,
// not an item-count estimate, so the fit below can GUARANTEE no clipping).
/** @param {Element} node @returns {number} */
const rowH = (node) => node.getBoundingClientRect().height;

/** @param {string} text @returns {HTMLElement} */
const moreLine = (text) => el("div", "agenda-more", text);

// Trim a day-row's events in place until the whole row fits `budget` px,
// appending a "+N more" line when any events are hidden. Used for the days we
// must never drop outright (today; the first upcoming day), so a single very
// busy day is shortened rather than removed — which is what keeps col 2 from
// ever ending up empty.
//
// Roll-off (today only — `.is-past` marks exist only there): already-past rows
// hide FIRST, oldest first, into a "+N earlier" line inserted where the first
// of them sat — i.e. BELOW the all-day/holiday pills (which sort before timed
// rows and never roll off), right where the timed list begins — so an
// overflowing afternoon reveals its hidden UPCOMING events instead of trimming
// them off the bottom. Demand-driven: on a day that fits, nothing rolls off,
// and it stops the moment the row fits. Only when every past row is gone and
// the row still overflows does the bottom "+N more" trim resume.
//
// The "+N …" lines are inserted with a placeholder label so measurement
// reserves their real height — an EMPTY div has no line box, so "" would
// under-reserve and the final label could push the row back over budget. Any
// one-line text measures the same.
/** @param {Element} dayRow @param {number} budget @returns {void} */
function fitDayInPlace(dayRow, budget) {
  if (rowH(dayRow) <= budget) return;
  const events = dayRow.querySelector(".day-events");
  if (!events || events.children.length === 0) return;
  const past = [...events.children].filter((c) => c.classList.contains("is-past"));
  /** @type {HTMLElement | null} */
  let earlier = null;
  if (past.length > 0) {
    earlier = moreLine("+0 earlier");
    past[0].before(earlier); // takes the oldest past row's place, below the pills
    let rolled = 0;
    for (const row of past) {
      if (rowH(dayRow) <= budget) break;
      row.remove();
      rolled += 1;
    }
    if (rolled > 0) earlier.textContent = `+${rolled} earlier`;
    else {
      earlier.remove();
      earlier = null;
    }
    if (rowH(dayRow) <= budget) return;
  }
  const more = moreLine("+0 more");
  events.append(more);
  let hidden = 0;
  while (rowH(dayRow) > budget && events.children.length > 1) {
    const last = events.children[events.children.length - 2]; // keep `more` last
    if (last === earlier) break; // never trim the roll-off summary itself
    last.remove();
    hidden += 1;
  }
  if (hidden > 0) more.textContent = `+${hidden} more`;
  else more.remove();
}

// Fit a column of day-rows into `budget` px without clipping. The first day is
// protected (its events are trimmed, never the whole day); later days that
// don't fit are dropped and summarized with a "+N more days" footer.
/** @param {Element} col @param {number} budget @returns {void} */
function fitColumnInPlace(col, budget) {
  const first = col.firstElementChild;
  if (!first) return;
  fitDayInPlace(first, budget); // today / first upcoming day — protected
  if (col.children.length < 2) return; // nothing droppable
  // Placeholder label so measurement reserves the footer's real line height
  // (same reasoning as in fitDayInPlace).
  const footer = moreLine("+0 more days");
  col.append(footer);
  let hiddenDays = 0;
  while (rowH(col) > budget && col.children.length > 1) {
    const last = col.children[col.children.length - 2]; // before footer
    if (last === first) break; // never drop the protected first day
    last.remove();
    hiddenDays += 1;
  }
  // Only label the footer if it actually fits; otherwise drop it (the protected
  // day's own "+N more" already signals truncation in that degenerate case).
  if (hiddenDays > 0 && rowH(col) <= budget) {
    footer.textContent = `+${hiddenDays} more day${hiddenDays === 1 ? "" : "s"}`;
  } else {
    footer.remove();
  }
}

/** @param {AgendaItem[]} events @param {boolean} [calendarOk] @param {boolean} [clockSynced] @returns {void} */
function renderAgenda(events, calendarOk = true, clockSynced = true) {
  // Guarantee today leads so column 1 always shows today (and can render the
  // quiet-day "Nothing today" when today has no events at all).
  const groups = withTodayGroup(groupByDay(events), localDayKey());
  const [col1, col2] = splitColumns(groups);
  const root = document.getElementById("agenda-body");
  root.replaceChildren();
  const cols = [];
  for (const col of [col1, col2]) {
    const colEl = el("div", "agenda-col");
    for (const group of col) colEl.append(dayRowNode(group, calendarOk, clockSynced));
    root.append(colEl);
    cols.push(colEl);
  }
  // Measure-and-fit pass (after layout, so heights are real): neither column
  // may clip. col 1 = today (events trimmed if needed); col 2 = upcoming days,
  // first one protected, the rest summarized as "+N more days".
  const budget = root.clientHeight;
  if (budget > 0) for (const colEl of cols) fitColumnInPlace(colEl, budget);
}

// Build the "<dot> Label" source indicator. Label is an own value, but built
// with el()/textContent + setAttribute for consistency with the safe pattern.
/** @param {string} label @param {boolean} ok @returns {HTMLElement} */
function srcNode(label, ok) {
  const src = el("span", "src");
  const dot = el("span", "dot" + (ok ? "" : " stale"));
  dot.setAttribute("title", label.toLowerCase());
  src.append(dot, el("span", "lbl", label));
  return src;
}

// `opts.stale` forces an all-stale, "Updated —" row (used when the fetch fails
// so the kiosk degrades visibly rather than showing a blank panel).
/** @param {DashboardDoc | null} data @param {{ stale?: boolean }} [opts] @returns {void} */
function renderStatus(data, opts = {}) {
  /** @type {[string, WeatherBlock | CalendarBlock | null][]} */
  const sources = [
    ["Weather", data && data.weather],
    ["Calendar", data && data.calendar],
  ];

  // "Updated" = the OLDEST fetched_at among OK sources (pickUpdated) so the
  // stamp can't over-claim freshness; rendered from that string's LOCAL
  // wall-clock part (not the Pi clock). opts.stale forces "—".
  const chosen = opts.stale ? null : pickUpdated(sources.map(([, s]) => s));
  const updated = chosen ? fmtLong(localParts(chosen).time) : "—";

  const status = document.getElementById("status");
  status.replaceChildren();
  for (const [label, s] of sources) status.append(srcNode(label, !opts.stale && s && s.ok));
  status.append(el("span", "sep", "·"), el("span", null, `Updated ${updated}`));

  const refresh = el("span", "refresh");
  refresh.setAttribute("title", "refresh");
  refresh.setAttribute("role", "button");
  refresh.innerHTML = REFRESH_SVG; // trusted backend/own SVG markup only — never interpolate calendar/user strings here.
  // Reflect an in-flight manual refresh: renderStatus rebuilds this node on every
  // poll, so the spin can't live only on the old node — re-derive it from the
  // module flag each render so a repaint mid-refresh keeps spinning.
  if (refreshing) refresh.classList.add("is-spinning");
  refresh.addEventListener("click", onRefresh); // tap → click (Chromium synthesizes it from wl_touch even with mouseEmulation="no")
  status.append(refresh);
}

// ── manual refresh ─────────────────────────────────────────────────────────

// True while a manual POST /refresh is in flight. Guards against a double-tap (or
// a poll-driven repaint) starting a second concurrent refresh, and is the source
// of truth for the spin state across renderStatus rebuilds.
let refreshing = false;

// Toggle the spin class on whatever .refresh node is currently mounted (the node
// identity changes across repaints, so re-query rather than capturing it).
/** @param {boolean} on @returns {void} */
function setRefreshSpinning(on) {
  const r = document.querySelector("#status .refresh");
  if (r) r.classList.toggle("is-spinning", on);
}

// Briefly flag the control red so a failed refresh isn't silent on a kiosk with
// no visible console. Cleared after a beat; a repaint in between is harmless.
function flashRefreshError() {
  const r = document.querySelector("#status .refresh");
  if (!r) return;
  r.classList.add("is-error");
  setTimeout(() => {
    const cur = document.querySelector("#status .refresh");
    if (cur) cur.classList.remove("is-error");
  }, 1500);
}

// Force an immediate backend refetch of every source, then reload the contract to
// repaint. POST /refresh is serialized server-side (asyncio.Lock) against the
// background loop, so this can't race a scheduled tick into a double-fetch.
async function onRefresh() {
  if (refreshing) return; // ignore taps while one is already running
  refreshing = true;
  setRefreshSpinning(true);
  try {
    const res = await fetch("/refresh", { method: "POST", cache: "no-store" });
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    await load(); // repaint with the freshly-refreshed doc (rebuilds the spinning node)
  } catch (err) {
    console.error("manual refresh failed:", err);
    flashRefreshError();
  } finally {
    refreshing = false;
    setRefreshSpinning(false);
  }
}

// ── boot ─────────────────────────────────────────────────────────────────────

// True once at least one fetch has painted real data. Drives how failures
// degrade: BEFORE the first success (the cold-boot 503 window) we show honest
// "unavailable" placeholders in EVERY data region; AFTER it, a failed poll
// leaves the last-good render on screen and only flips the freshness dots stale
// — so weather and the agenda degrade alike, never one wiped while the other stays.
let hasRendered = false;

// Last clock_synced value the API reported (true/false/undefined). When the
// backend explicitly says false — the Pi clock isn't NTP-synced yet, e.g. the
// ~1-min post-boot window before timesyncd lands — `tick` polls at the short
// retry cadence instead of the 15-min one, so the "clock not synced" warning
// clears promptly after sync rather than at the next slow poll. undefined/true
// (dev host, older cache) is treated as fine.
let lastClockSynced;

// Cold-boot degrade: every data region gets an honest placeholder so nothing is
// a blank glass box (the weather hero/forecast used to stay empty here).
function renderUnavailable() {
  const current = document.getElementById("current-card");
  if (current) current.replaceChildren(el("div", "cur-unavailable", "Weather unavailable"));
  const forecast = document.getElementById("forecast");
  if (forecast) forecast.replaceChildren();
  const agenda = document.getElementById("agenda-body");
  if (agenda) agenda.replaceChildren(el("div", "agenda-empty", "Data unavailable"));
}

// Fetch the contract and repaint every data region. Returns true on success.
// On any failure (including the 503 the API returns before its first refresh
// tick) degrade visibly — stale dots, "Updated —", honest placeholders on cold
// boot, last-good kept otherwise — never a blank panel.
async function load() {
  try {
    const res = await fetch(DATA_URL, { cache: "no-store" });
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    // The untyped JSON boundary — assert the contract so the render pipeline
    // downstream is checked against DashboardDoc (mirrors the backend's typing).
    /** @type {DashboardDoc} */
    const data = await res.json();
    renderCurrent(data.weather);
    renderForecast(data.weather.forecast);
    renderAgenda(data.calendar.events, data.calendar.ok, data.clock_synced);
    renderStatus(data);
    lastClockSynced = data.clock_synced;
    setClockWarning(data.clock_synced);
    hasRendered = true;
    return true;
  } catch (err) {
    console.error("dashboard load failed:", err);
    renderStatus(null, { stale: true });
    // No good data has ever painted → honest placeholders. After a prior
    // success → leave the last-good render untouched; only the dots go stale.
    if (!hasRendered) renderUnavailable();
    return false;
  }
}

// Self-scheduling poll: on success, next fetch in POLL_INTERVAL_MS; on failure,
// retry in the shorter RETRY_INTERVAL_MS. A single timer chain (not setInterval)
// so a slow fetch can't stack overlapping polls.
async function tick() {
  const ok = await load();
  // Use the slow cadence only once we're settled: a successful load AND the Pi
  // clock is synced. A failed load or an explicit clock_synced===false keeps us
  // on the short retry cadence so both the cold-boot 503 window and the
  // pre-NTP-sync window clear in ~30s steps, not up to 15 min.
  const settled = ok && lastClockSynced !== false;
  setTimeout(tick, settled ? POLL_INTERVAL_MS : RETRY_INTERVAL_MS);
}

// The local day we last rendered for; flips at midnight to trigger a reload so
// the agenda rolls (today→tomorrow, new in-window holidays/events) without
// waiting for the next poll. The clock itself already ticks live each second.
let currentDay = null;

function init() {
  renderClock();
  renderBlackout();
  currentDay = localDayKey();
  setInterval(() => {
    renderClock();
    renderBlackout();
    const today = localDayKey();
    if (dayRolledOver(currentDay, today)) load();
    currentDay = today;
  }, 1000);
  tick();
}

// Browser-only bootstrap. Guarded so importing this module under node:test
// (for the pure-function unit tests) runs no DOM/init side effects.
if (typeof document !== "undefined") init();
