// Swiss-mono layout - the exposed-modular-grid design (design-mocks/swiss-mono.html),
// ported as a selectable layout. Exports a `layout` object implementing the
// seven-hook Layout interface (see core/contract.js): mount() builds the 2×3
// drafted-grid shell into the bare <div id="app">, and the per-region renderers
// fill it from the data contract.
//
// The "exposed grid" look is pure CSS (background:var(--ink); gap:1px) - no
// blur/glow, so it is thermal-safe on the Pi. Every human/PII string
// (current.text, forecast text, event title) is routed through textContent
// (never innerHTML); only OWN values touch markup: the weather-icon class (an
// attribute) and the static refresh SVG constant.
//
// Side-effect-free on import (the core graph's invariant, see core/machine.js):
// the DOM is touched only inside mount()/the render hooks, driven by init().

import { to12, pad2, fmtCompact, fmtCompactOr, fmtLong, localParts, localDate, localDayKey, dayLabel } from "../../core/time.js";
import {
  groupByDay,
  splitColumns,
  withTodayGroup,
  hasPersonalEvents,
  nextUp,
  pastIndexes,
  planDayFit,
  planColumnFit,
} from "../../core/agenda.js";
import { pickUpdated, fmtHiLo } from "../../core/format.js";
import { el } from "../../core/dom.js";

/** @typedef {import("../../core/contract.js").AgendaItem} AgendaItem */
/** @typedef {import("../../core/contract.js").WeatherBlock} WeatherBlock */
/** @typedef {import("../../core/contract.js").CalendarBlock} CalendarBlock */
/** @typedef {import("../../core/contract.js").ForecastDay} ForecastDay */
/** @typedef {import("../../core/contract.js").DashboardDoc} DashboardDoc */
/** @typedef {import("../../core/contract.js").StatusOpts} StatusOpts */
/** @typedef {import("../../core/agenda.js").DayGroup} DayGroup */
/** @typedef {import("../../core/contract.js").IconPack} IconPack */

// The icon pack injected at mount (core/contract.js IconPack). The current +
// forecast condition glyphs route through iconPack.renderIcon, so this layout
// never names a pack - swapping ICON_PACK upstream reskins them. Set in mount.
/** @type {IconPack} */
let iconPack;

// ── shell ────────────────────────────────────────────────────────────────────

// Build the swiss-mono DOM shell into the bare mount root: the 2-col × 3-row
// exposed grid. Left column = TIME (row1) over CURRENT (row2); right column =
// FORECAST (row1) over AGENDA (row2); STATUS footer spans both columns (row3).
// Source order below drives the grid auto-placement to that arrangement. The
// id'd region containers are filled by the renderers; only the shell + the
// static "Upcoming" agenda tag are built here.
/** @param {HTMLElement} root @param {{ icon: IconPack }} ctx @returns {void} */
function mount(root, ctx) {
  iconPack = ctx.icon;
  const screen = el("div", "screen swiss-mono");

  // 01 / TIME - big clock + long date (+ the hidden clock-not-synced warning).
  const time = el("section", "cell time");
  const clock = el("div", "clock");
  clock.id = "clock";
  const date = el("div", "clock-date");
  date.id = "clock-date";
  // Shown only while the Pi clock is NOT NTP-synced (clock_synced=false); the
  // big clock ticks from the browser and would be wrong. (The mock has none -
  // added like classic's #clock-warn.)
  const warn = el("div", "clock-warn", "clock not yet synced");
  warn.id = "clock-warn";
  warn.hidden = true;
  time.append(clock, date, warn);

  // 03–06 / FORECAST - 4 equal cells (filled by renderForecast).
  const forecast = el("section", "cell forecast");
  forecast.id = "forecast";

  // 02 / CURRENT - hero temp + condition + 8-cell meta grid (renderCurrent).
  const current = el("section", "cell current");
  current.id = "current";

  // 07 / AGENDA - static "Upcoming" tag + the two 50/50 sub-columns body.
  const agenda = el("section", "cell agenda");
  const body = el("div", "agenda-cols");
  body.id = "agenda-body";
  agenda.append(el("span", "tag", "Upcoming"), body);

  // STATUS - spans both columns (row3).
  const status = el("footer", "cell status");
  status.id = "status";

  screen.append(time, forecast, current, agenda, status);
  root.append(screen);
}

// ── inline SVG (refresh) - own static markup, never interpolated ──────────────

const REFRESH_SVG =
  '<svg viewBox="0 0 24 24" aria-hidden="true" stroke-linecap="round" stroke-linejoin="round">' +
  '<path d="M19.5 12A7.5 7.5 0 1 1 16.6 6.2"/><polyline points="16.9 2.6 16.9 6.5 13 6.5"/></svg>';

// ── DOM builders ─────────────────────────────────────────────────────────────

// One cell of the 8-cell current-weather meta grid: uppercase key + value. Both
// set via el()/textContent - never interpolated as HTML.
/** @param {string} label @param {string} value @returns {HTMLElement} */
function metaItem(label, value) {
  const item = el("div", "meta-item");
  item.append(el("span", "meta-k", label), el("span", "meta-v", value));
  return item;
}

// "+N …" agenda summary line (mock's muted mono marker). The arrow prefixes are
// real vendored-font glyphs (↑ U+2191 / ↓ U+2193). `extra` tags the column
// footer (mock's .marker.days) so it can carry its own top rule.
/** @param {string} text @param {string} [extra] @returns {HTMLElement} */
const moreLine = (text, extra) => el("div", "agenda-more" + (extra ? " " + extra : ""), text);

// One agenda event row. Holiday/observance items are pulled into the day header
// as pills (see dayBlockNode); `info` kind renders as a muted marker line.
// `isNext` marks the next-up event (the red "● NOW" row), `isPast` tags an
// already-past row for the roll-off pass - both apply only to a timed personal
// row (the only kind nextUp/pastIndexes ever select).
/** @param {AgendaItem} ev @param {boolean} [isNext] @param {boolean} [isPast] @returns {HTMLElement} */
function eventNode(ev, isNext = false, isPast = false) {
  // DST / informational marker -> plain muted line.
  if (ev.kind === "info") {
    return el("div", "marker", ev.title); // title as text (textContent) - never HTML
  }
  const { time } = localParts(ev.start);
  const allday = ev.all_day || !time;
  const row = el("div", "ev" + (isNext ? " now" : "") + (isPast ? " is-past" : ""));
  const when = allday ? el("span", "ev-t allday", "All day") : el("span", "ev-t", fmtCompact(time));
  row.append(when, el("span", "ev-n", ev.title)); // title as text (textContent) - never HTML
  // The ● (U+25CF) is a vendored JetBrains Mono glyph - emitted as text.
  if (isNext) row.append(el("span", "ev-nowtag", "● NOW"));
  return row;
}

// One day block: a head (day name/date + holiday pills) above its .day-events
// list. The head sits OUTSIDE .day-events so the fit shell's roll-off never
// trims the pills - matching classic/hud.
/** @param {DayGroup} group @param {boolean} [calendarOk] @param {boolean} [clockSynced] @returns {HTMLElement} */
function dayBlockNode(group, calendarOk = true, clockSynced = true) {
  const { isToday, dname, ddate } = dayLabel(group.date);
  const block = el("div", "ag-block" + (isToday ? " is-today" : ""));

  // Partition the day's items once: holiday/observance -> header pills,
  // personal/info -> event rows (matching hud's daySection).
  const pills = group.items.filter((i) => i.kind === "holiday" || i.kind === "observance");
  const rows = group.items.filter((i) => i.kind === "personal" || i.kind === "info");

  const head = el("div", "ag-head");
  head.append(el("span", "ag-day", dname), el("span", "ag-date", ddate));
  // Holidays/observances become header pills (identical weight - kind stays
  // distinct in the data as provenance only). title as text - never HTML.
  for (const p of pills) head.append(el("span", "pill", p.title));

  const events = el("div", "day-events");
  // "Today awareness": the next-up highlight and the roll-off candidates share
  // one gate - TODAY only, and only when the clock is trustworthy - and one
  // `now`. Picked by object identity (not index) because pills are partitioned
  // out above, so raw nextUp/pastIndexes indices wouldn't map to the rows.
  const aware = isToday && clockSynced !== false;
  const now = new Date();
  const nextIdx = aware ? nextUp(group.items, now) : -1;
  const nextEv = nextIdx >= 0 ? group.items[nextIdx] : null;
  const pastSet = new Set(aware ? pastIndexes(group.items, now).map((i) => group.items[i]) : []);
  for (const ev of rows) events.append(eventNode(ev, ev === nextEv, pastSet.has(ev)));

  // Quiet-day state: today with no personal events gets a friendly "Nothing
  // today" (any holiday pill above still shows as context). Only when the
  // calendar fetched OK - on a stale/failed calendar we don't know today's
  // events, so we don't claim emptiness.
  if (isToday && calendarOk && !hasPersonalEvents(group.items)) {
    events.append(el("div", "day-empty", "Nothing today"));
  }
  block.append(head, events);
  return block;
}

// ── region renderers ─────────────────────────────────────────────────────────

// Live wall-clock from the browser (the one time source NOT taken from the API),
// plus the clock-sync warning. `synced` false -> show the warning (Pi clock not
// NTP-synced yet); true/unknown -> hide it.
/** @param {Date} now @param {boolean} synced @returns {void} */
function renderClock(now, synced) {
  const { h, ampm } = to12(now.getHours());
  // h/minutes are own numbers; build via el()/textContent so no human/contract
  // text is ever interpolated into markup here.
  const clock = document.getElementById("clock");
  if (clock) clock.replaceChildren(el("span", "clock-big", `${h}:${pad2(now.getMinutes())}`), el("span", "clock-mer", ampm));
  const date = document.getElementById("clock-date");
  if (date) date.textContent = now.toLocaleDateString(undefined, {
    weekday: "long",
    month: "long",
    day: "numeric",
  });
  // Guard the write: the core drives renderClock every second, but the sync
  // state changes rarely, so only touch #clock-warn.hidden when it flips (a
  // plain idempotent write would repaint-poke the node each tick).
  const warn = document.getElementById("clock-warn");
  if (warn && warn.hidden !== synced) warn.hidden = synced;
}

/** @param {WeatherBlock} weather @returns {void} */
function renderCurrent(weather) {
  const c = weather.current;
  const cell = document.getElementById("current");
  if (!cell) return;
  cell.replaceChildren();

  const top = el("div", "cur-top");
  const temp = el("div", "cur-temp");
  temp.append(String(c.temp_f), el("span", "deg", "°")); // own numbers only
  const iconblock = el("div", "cur-iconblock");
  iconblock.append(iconPack.renderIcon(c.icon, "cur-icon"));
  top.append(temp, iconblock);

  const cond = el("div", "cur-cond");
  cond.append(c.text); // c.text is HUMAN TEXT - textContent, never innerHTML

  // 8-cell meta grid. High/Low live HERE (not beside the hero temp), unlike
  // classic - see the mock. High/Low via fmtHiLo; sunrise/sunset via localParts.
  const { hi, lo } = fmtHiLo(c);
  const meta = el("div", "meta");
  meta.append(
    metaItem("High", hi.temp),
    metaItem("Low", lo.temp),
    metaItem("Feels like", `${c.feels_like_f}°`),
    metaItem("Rain", `${c.precip_prob_pct}%`),
    metaItem("Humidity", `${c.humidity_pct}%`),
    metaItem("Wind", `${c.wind_mph} mph`),
    metaItem("Sunrise", fmtCompactOr(localParts(c.sunrise).time)),
    metaItem("Sunset", fmtCompactOr(localParts(c.sunset).time)),
  );

  cell.append(top, cond, meta);
}

/** @param {ForecastDay[]} forecast @returns {void} */
function renderForecast(forecast) {
  const root = document.getElementById("forecast");
  if (!root) return;
  root.replaceChildren();
  // The grid is a fixed repeat(4,1fr); slice defensively so a short/long feed
  // never misaligns it.
  for (const f of forecast.slice(0, 4)) {
    const dname = localDate(f.date).toLocaleDateString(undefined, { weekday: "long" });
    const card = el("div", "fc");

    const { hi, lo } = fmtHiLo(f);
    const temps = el("div", "fc-temps");
    temps.append(el("span", "fc-hi", hi.temp), el("span", "fc-lo", `/ ${lo.temp}`));

    const foot = el("div", "fc-foot");
    foot.append(el("div", "fc-cond", f.text)); // f.text is HUMAN TEXT - textContent
    // Precip line shown ONLY on codes that precipitate (backend is_wet gate);
    // an absent flag reads dry. The % is an OWN number.
    if (f.precip_expected) {
      const precip = el("div", "fc-precip");
      precip.append("PRECIP ", el("b", null, `${f.precip_prob_pct}%`));
      foot.append(precip);
    }

    // day (top) · icon · temps · condition+precip foot (bottom).
    card.append(el("div", "fc-day", dname), iconPack.renderIcon(f.icon, "fc-icon"), temps, foot);
    root.append(card);
  }
}

// ── agenda fit shells (DOM around the pure planners) ──────────────────────────

// Measured render height of a node (real px - the fit can GUARANTEE no clip).
/** @param {Element} node @returns {number} */
const rowH = (node) => node.getBoundingClientRect().height;

// Height a "+N …" summary line will occupy in `container`, measured with a real
// (briefly attached) placeholder - an estimate could under-reserve. Any one-line
// text measures the same, so "+0 more" stands in for every label. `extra` must
// match the real footer's modifier: the column footer is `moreLine(…, "days")`,
// whose `.days` rule adds a top margin + heavier padding rule. getBoundingClientRect
// EXCLUDES margin, so add the computed top margin back - otherwise the reserved
// height falls ~30px short of the real footer's outer box and it clips.
/** @param {Element} container @param {string} [extra] @returns {number} */
function measureLine(container, extra) {
  const probe = moreLine("+0 more", extra);
  container.append(probe);
  // getComputedStyle is a direct global call so it keeps its window `this` in the
  // browser; guarded via typeof for the headless test stub (no CSSOM), which reads
  // margin as 0 - real browsers always have it.
  const marginTop =
    typeof getComputedStyle === "function" ? parseFloat(getComputedStyle(probe).marginTop || "0") : 0;
  const h = rowH(probe) + marginTop;
  probe.remove();
  return h;
}

// Trim a day-block's events in place until the whole block fits `budget` px -
// the imperative shell around the pure `planDayFit` (its roll-off/trim
// contract). The head (with its pills) sits outside .day-events, so it is never
// trimmed. Used for the days we must never drop outright (today; the first
// upcoming day), so a busy day is shortened rather than removed.
/** @param {Element} block @param {number} budget @returns {void} */
function fitDayInPlace(block, budget) {
  const events = block.querySelector(".day-events");
  if (!events || events.children.length === 0) return;
  const children = [...events.children];
  const plan = planDayFit(
    rowH(block),
    children.map(rowH),
    children.map((c) => c.classList.contains("is-past")),
    measureLine(events),
    budget,
  );
  if (plan.earlierCount > 0) {
    // Takes the oldest past row's place - right where the timed list begins.
    const firstPast = children.find((c) => c.classList.contains("is-past"));
    if (firstPast) firstPast.before(moreLine(`↑ +${plan.earlierCount} earlier`));
  }
  for (const i of plan.hide) children[i].remove();
  if (plan.moreCount > 0) events.append(moreLine(`↓ +${plan.moreCount} more`));
}

// Fit a column of day-blocks into `budget` px without clipping - the imperative
// shell around the pure `planColumnFit`. The first day is protected (its events
// are trimmed via fitDayInPlace, never the whole day); later days that don't fit
// are dropped and summarized with a "↓ +N more days" footer.
/** @param {Element} col @param {number} budget @returns {void} */
function fitColumnInPlace(col, budget) {
  const first = col.firstElementChild;
  if (!first) return;
  fitDayInPlace(first, budget); // today / first upcoming day - protected
  const days = [...col.children];
  // Measure the footer WITH its real `.days` modifier so the reservation matches
  // the `moreLine(…, "days")` appended below (margin + heavier rule included).
  const plan = planColumnFit(rowH(col), days.map(rowH), measureLine(col, "days"), budget);
  for (let k = 0; k < plan.dropCount; k++) days[days.length - 1 - k].remove();
  if (plan.showFooter) {
    const n = plan.dropCount;
    col.append(moreLine(`↓ +${n} more day${n === 1 ? "" : "s"}`, "days"));
  }
}

/** @param {AgendaItem[]} events @param {boolean} [calendarOk] @param {boolean} [clockSynced] @returns {void} */
function renderAgenda(events, calendarOk = true, clockSynced = true) {
  // Guarantee today leads so column 1 always shows today (and can render the
  // quiet-day "Nothing today" when today has no events at all).
  const groups = withTodayGroup(groupByDay(events), localDayKey());
  const [col1, col2] = splitColumns(groups);
  const root = document.getElementById("agenda-body");
  if (!root) return;
  root.replaceChildren();
  // Each column is a stretched paper "tile" (a grid item that fills the cell
  // full-height for the exposed-grid look, overflow-clipped) wrapping a
  // NATURAL-height body. The fit shell must measure the BODY, not the tile:
  // a grid item stretches to its row, so rowH(tile) would read the full budget
  // and defeat planColumnFit (it'd see no overflow and never trim). The body is
  // flex:0 0 auto, so its rowH is the true content height; its own padding is
  // inside that measurement, so the column fit reserves it. col2 gets the .rt
  // modifier (its "+N more days" footer carries a heavier top rule, per the mock).
  const bodies = /** @type {HTMLElement[]} */ ([]);
  const specs = /** @type {[DayGroup[], string][]} */ ([[col1, "ag-col"], [col2, "ag-col rt"]]);
  for (const [col, cls] of specs) {
    const tile = el("div", cls);
    const body = el("div", "ag-col-body");
    for (const group of col) body.append(dayBlockNode(group, calendarOk, clockSynced));
    tile.append(body);
    root.append(tile);
    bodies.push(body);
  }
  // Measure-and-fit pass (after layout, so heights are real): neither column
  // may clip. col1 = today (events trimmed if needed); col2 = upcoming days,
  // first protected, the rest summarized as "+N more days".
  const budget = root.clientHeight;
  if (budget > 0) for (const body of bodies) fitColumnInPlace(body, budget);
}

// ── status + manual refresh ──────────────────────────────────────────────────

// True while a manual POST /refresh is in flight. Guards a double-tap (or a
// poll-driven repaint) starting a second concurrent refresh, and is the source
// of truth for the spin state across renderStatus rebuilds.
let refreshing = false;

// The core's refresh primitive, captured from the latest renderStatus opts so
// the (stable) click handler always calls the current one.
/** @type {(() => Promise<void>) | null} */
let coreRefresh = null;

// Toggle the spin class on whatever .refresh node is currently mounted (the node
// identity changes across repaints, so re-query rather than capturing it).
/** @param {boolean} on @returns {void} */
function setRefreshSpinning(on) {
  const r = document.querySelector("#status .refresh");
  if (r) r.classList.toggle("is-spinning", on);
}

// Briefly flag the control red so a failed refresh isn't silent on a kiosk with
// no visible console. Cleared after a beat; a repaint in between is harmless.
/** @returns {void} */
function flashRefreshError() {
  const r = document.querySelector("#status .refresh");
  if (!r) return;
  r.classList.add("is-error");
  setTimeout(() => {
    const cur = document.querySelector("#status .refresh");
    if (cur) cur.classList.remove("is-error");
  }, 1500);
}

// Drive the manual refresh: spin, invoke the core's refresh primitive (POST
// /refresh + reload - which rebuilds this node, still spinning via `refreshing`),
// flash red on failure, then stop. Serialized against itself by `refreshing`.
/** @returns {Promise<void>} */
async function onRefresh() {
  if (refreshing) return; // ignore taps while one is already running
  refreshing = true;
  setRefreshSpinning(true);
  try {
    if (coreRefresh) await coreRefresh();
  } catch (err) {
    console.error("manual refresh failed:", err);
    flashRefreshError();
  } finally {
    refreshing = false;
    setRefreshSpinning(false);
  }
}

// One "■ LABEL OK/STALE" source indicator. The ■ is a styled .st-sq span (not a
// glyph); the label is an own value but built via el()/textContent for
// consistency with the safe pattern.
/** @param {string} label @param {boolean} ok @returns {HTMLElement} */
function srcNode(label, ok) {
  const item = el("span", "st-item" + (ok ? "" : " stale"));
  item.append(el("span", "st-sq" + (ok ? "" : " stale")), `${label} ${ok ? "ok" : "stale"}`);
  return item;
}

// `opts.stale` forces an all-stale, dashed "Updated" row (used when the fetch
// fails so the kiosk degrades visibly rather than showing a blank panel).
// `opts.refresh` is the core's refresh primitive the control wires to.
/** @param {DashboardDoc | null} data @param {StatusOpts} [opts] @returns {void} */
function renderStatus(data, opts = {}) {
  coreRefresh = opts.refresh ?? null;
  /** @type {[string, WeatherBlock | CalendarBlock | null][]} */
  const sources = [
    ["Weather", data && data.weather],
    ["Calendar", data && data.calendar],
  ];

  // "Updated" = the OLDEST fetched_at among OK sources (pickUpdated) so the
  // stamp can't over-claim freshness; rendered from that string's LOCAL
  // wall-clock part (not the Pi clock). opts.stale forces "—".
  const chosen = opts.stale ? null : pickUpdated(sources.map(([, s]) => s));
  // A chosen stamp is always a datetime (fetched_at), but guard the date-only
  // shape (time null) the same way the sunrise/sunset cells do.
  const time = chosen ? localParts(chosen).time : null;
  const updated = time ? fmtLong(time) : "—";

  const status = document.getElementById("status");
  if (!status) return;
  status.replaceChildren();
  for (const [label, s] of sources)
    status.append(srcNode(label, Boolean(!opts.stale && s && s.ok)));
  status.append(el("span", "st-updated", `Updated ${updated}`));

  const refresh = el("button", "refresh");
  refresh.setAttribute("type", "button");
  refresh.setAttribute("title", "refresh");
  refresh.innerHTML = REFRESH_SVG; // trusted own SVG markup only - never interpolate calendar/user strings here.
  refresh.append("Refresh");
  // Reflect an in-flight manual refresh: renderStatus rebuilds this node on
  // every poll, so re-derive the spin from the module flag each render.
  if (refreshing) refresh.classList.add("is-spinning");
  refresh.addEventListener("click", onRefresh); // tap → click (synthesized from wl_touch)
  status.append(refresh);
}

// Cold-boot degrade: every data region gets an honest placeholder so no cell is
// left blank (the drafted grid would otherwise show empty paper cells).
/** @returns {void} */
function renderUnavailable() {
  const current = document.getElementById("current");
  if (current) current.replaceChildren(el("div", "cur-unavailable", "Weather unavailable"));
  const forecast = document.getElementById("forecast");
  // One placeholder spanning all four forecast columns (CSS grid-column:1/-1) so
  // no ink cell is left empty.
  if (forecast) forecast.replaceChildren(el("div", "fc-unavailable", "Forecast unavailable"));
  const agenda = document.getElementById("agenda-body");
  if (agenda) agenda.replaceChildren(el("div", "agenda-empty", "Data unavailable"));
}

/** @type {import("../../core/contract.js").Layout} */
export const layout = {
  mount,
  renderClock,
  renderCurrent,
  renderForecast,
  renderAgenda,
  renderStatus,
  renderUnavailable,
};
