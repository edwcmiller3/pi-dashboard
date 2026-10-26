// Swiss-mono layout (exposed modular grid), implementing the Layout contract
// (core/contract.js). The grid look is pure CSS (ink background + 1px gaps) - no
// blur/glow, so it's thermal-safe on the Pi. Human/PII strings go through
// textContent only; just own static SVG touches markup.
//
// Side-effect-free on import (see core/machine.js).

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
import { go } from "../../core/router.js";
import { SETTINGS_SVG } from "../../core/chrome.js";

/** @typedef {import("../../core/contract.js").AgendaItem} AgendaItem */
/** @typedef {import("../../core/contract.js").WeatherBlock} WeatherBlock */
/** @typedef {import("../../core/contract.js").CalendarBlock} CalendarBlock */
/** @typedef {import("../../core/contract.js").ForecastDay} ForecastDay */
/** @typedef {import("../../core/contract.js").DashboardDoc} DashboardDoc */
/** @typedef {import("../../core/contract.js").StatusOpts} StatusOpts */
/** @typedef {import("../../core/agenda.js").DayGroup} DayGroup */
/** @typedef {import("../../core/contract.js").IconPack} IconPack */

// Injected at mount; condition glyphs route through it so this layout never names a pack.
/** @type {IconPack} */
let iconPack;

// ── shell ────────────────────────────────────────────────────────────────────

// 2-col × 3-row grid: TIME over CURRENT (left), FORECAST over AGENDA (right),
// STATUS spanning row 3. Source order drives auto-placement into that arrangement.
/** @param {HTMLElement} root @param {{ icon: IconPack }} ctx @returns {void} */
function mount(root, ctx) {
  iconPack = ctx.icon;
  const screen = el("div", "screen swiss-mono");

  const time = el("section", "cell time");
  const clock = el("div", "clock");
  clock.id = "clock";
  const date = el("div", "clock-date");
  date.id = "clock-date";
  // Shown while the Pi clock isn't NTP-synced: the clock ticks from the browser.
  const warn = el("div", "clock-warn", "clock not yet synced");
  warn.id = "clock-warn";
  warn.hidden = true;
  time.append(clock, date, warn);

  const forecast = el("section", "cell forecast");
  forecast.id = "forecast";

  const current = el("section", "cell current");
  current.id = "current";

  const agenda = el("section", "cell agenda");
  const body = el("div", "agenda-cols");
  body.id = "agenda-body";
  agenda.append(el("span", "tag", "Upcoming"), body);

  const status = el("footer", "cell status");
  status.id = "status";
  adminCog = cogNode();
  status.append(adminCog);

  screen.append(time, forecast, current, agenda, status);
  root.append(screen);
}

// ── inline SVG (refresh) ─────────────────────────────────────────────────────

const REFRESH_SVG =
  '<svg viewBox="0 0 24 24" aria-hidden="true" stroke-linecap="round" stroke-linejoin="round">' +
  '<path d="M19.5 12A7.5 7.5 0 1 1 16.6 6.2"/><polyline points="16.9 2.6 16.9 6.5 13 6.5"/></svg>';

// ── DOM builders ─────────────────────────────────────────────────────────────

/** @param {string} label @param {string} value @returns {HTMLElement} */
function metaItem(label, value) {
  const item = el("div", "meta-item");
  item.append(el("span", "meta-k", label), el("span", "meta-v", value));
  return item;
}

// The ↑/↓ prefixes are in the vendored font, so they're safe as text. `extra`
// tags the column footer (.days) so it can carry its own top rule.
/** @param {string} text @param {string} [extra] @returns {HTMLElement} */
const moreLine = (text, extra) => el("div", "agenda-more" + (extra ? " " + extra : ""), text);

// Personal/info rows only - holidays become day-header pills. `isPast` marks a
// row for the roll-off pass.
/** @param {AgendaItem} ev @param {boolean} [isNext] @param {boolean} [isPast] @returns {HTMLElement} */
function eventNode(ev, isNext = false, isPast = false) {
  if (ev.kind === "info") {
    return el("div", "marker", ev.title);
  }
  const { time } = localParts(ev.start);
  const allday = ev.all_day || !time;
  const row = el("div", "ev" + (isNext ? " now" : "") + (isPast ? " is-past" : ""));
  const when = allday ? el("span", "ev-t allday", "All day") : el("span", "ev-t", fmtCompact(time));
  row.append(when, el("span", "ev-n", ev.title)); // title as text (textContent) - never HTML
  // ● is in the vendored JetBrains Mono subset, so it's safe as text.
  if (isNext) row.append(el("span", "ev-nowtag", "● NOW"));
  return row;
}

// The head sits outside .day-events so the fit's roll-off never trims the pills.
/** @param {DayGroup} group @param {boolean} [calendarOk] @param {boolean} [clockSynced] @returns {HTMLElement} */
function dayBlockNode(group, calendarOk = true, clockSynced = true) {
  const { isToday, dname, ddate } = dayLabel(group.date);
  const block = el("div", "ag-block" + (isToday ? " is-today" : ""));

  const pills = group.items.filter((i) => i.kind === "holiday" || i.kind === "observance");
  const rows = group.items.filter((i) => i.kind === "personal" || i.kind === "info");

  const head = el("div", "ag-head");
  head.append(el("span", "ag-day", dname), el("span", "ag-date", ddate));
  for (const p of pills) head.append(el("span", "pill", p.title));

  const events = el("div", "day-events");
  // One gate and one `now` for next-up and roll-off. Matched by identity because
  // nextUp/pastIndexes index the full list, not the partitioned `rows`.
  const aware = isToday && clockSynced !== false;
  const now = new Date();
  const nextIdx = aware ? nextUp(group.items, now) : -1;
  const nextEv = nextIdx >= 0 ? group.items[nextIdx] : null;
  const pastSet = new Set(aware ? pastIndexes(group.items, now).map((i) => group.items[i]) : []);
  for (const ev of rows) events.append(eventNode(ev, ev === nextEv, pastSet.has(ev)));

  // Only claim emptiness when the calendar fetched OK - a stale feed doesn't know.
  if (isToday && calendarOk && !hasPersonalEvents(group.items)) {
    events.append(el("div", "day-empty", "Nothing today"));
  }
  block.append(head, events);
  return block;
}

// ── region renderers ─────────────────────────────────────────────────────────

// The browser clock is the one time source not taken from the API.
/** @param {Date} now @param {boolean} synced @returns {void} */
function renderClock(now, synced) {
  const { h, ampm } = to12(now.getHours());
  const clock = document.getElementById("clock");
  if (clock) clock.replaceChildren(el("span", "clock-big", `${h}:${pad2(now.getMinutes())}`), el("span", "clock-mer", ampm));
  const date = document.getElementById("clock-date");
  if (date) date.textContent = now.toLocaleDateString(undefined, {
    weekday: "long",
    month: "long",
    day: "numeric",
  });
  // Write only on change: this runs every second, and an idempotent write would
  // still poke the node each tick.
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
  temp.append(String(c.temp_f), el("span", "deg", "°"));
  const iconblock = el("div", "cur-iconblock");
  iconblock.append(iconPack.renderIcon(c.icon, "cur-icon"));
  top.append(temp, iconblock);

  const cond = el("div", "cur-cond");
  cond.append(c.text); // human text - textContent only

  // Unlike classic, High/Low live in the meta grid, not beside the hero temp.
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
  // The grid is a fixed repeat(4,1fr); slice so a long feed can't misalign it.
  for (const f of forecast.slice(0, 4)) {
    const dname = localDate(f.date).toLocaleDateString(undefined, { weekday: "long" });
    const card = el("div", "fc");

    const { hi, lo } = fmtHiLo(f);
    const temps = el("div", "fc-temps");
    temps.append(el("span", "fc-hi", hi.temp), el("span", "fc-lo", `/ ${lo.temp}`));

    const foot = el("div", "fc-foot");
    foot.append(el("div", "fc-cond", f.text)); // human text - textContent only
    // Precip line only on wet codes (backend is_wet gate); absent flag = dry.
    if (f.precip_expected) {
      const precip = el("div", "fc-precip");
      precip.append("PRECIP ", el("b", null, `${f.precip_prob_pct}%`));
      foot.append(precip);
    }

    card.append(el("div", "fc-day", dname), iconPack.renderIcon(f.icon, "fc-icon"), temps, foot);
    root.append(card);
  }
}

// ── agenda fit shells (DOM around the pure planners) ──────────────────────────

// Real measured px (not an estimate), so the fit can guarantee no clipping.
/** @param {Element} node @returns {number} */
const rowH = (node) => node.getBoundingClientRect().height;

// Measured with a briefly attached probe - an estimate could under-reserve; any
// one-line text measures the same. `extra` must match the real footer's modifier:
// `.days` adds a top margin, which getBoundingClientRect excludes, so it's added
// back - otherwise the reservation falls ~30px short and the footer clips.
/** @param {Element} container @param {string} [extra] @returns {number} */
function measureLine(container, extra) {
  const probe = moreLine("+0 more", extra);
  container.append(probe);
  // Called as a bare global so it keeps its window `this`; the typeof guard is
  // for the headless test stub (no CSSOM).
  const marginTop =
    typeof getComputedStyle === "function" ? parseFloat(getComputedStyle(probe).marginTop || "0") : 0;
  const h = rowH(probe) + marginTop;
  probe.remove();
  return h;
}

// DOM shell around the pure planDayFit, for days never dropped outright (today,
// first upcoming day) - a busy day is shortened rather than removed.
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
    // In the oldest past row's place, where the timed list begins.
    const firstPast = children.find((c) => c.classList.contains("is-past"));
    if (firstPast) firstPast.before(moreLine(`↑ +${plan.earlierCount} earlier`));
  }
  for (const i of plan.hide) children[i].remove();
  if (plan.moreCount > 0) events.append(moreLine(`↓ +${plan.moreCount} more`));
}

// DOM shell around the pure planColumnFit. The first day is trimmed, never
// dropped; later days that don't fit collapse into a "↓ +N more days" footer.
/** @param {Element} col @param {number} budget @returns {void} */
function fitColumnInPlace(col, budget) {
  const first = col.firstElementChild;
  if (!first) return;
  fitDayInPlace(first, budget);
  const days = [...col.children];
  // Measure with the real `.days` modifier so the reservation matches the footer.
  const plan = planColumnFit(rowH(col), days.map(rowH), measureLine(col, "days"), budget);
  for (let k = 0; k < plan.dropCount; k++) days[days.length - 1 - k].remove();
  if (plan.showFooter) {
    const n = plan.dropCount;
    col.append(moreLine(`↓ +${n} more day${n === 1 ? "" : "s"}`, "days"));
  }
}

/** @param {AgendaItem[]} events @param {boolean} [calendarOk] @param {boolean} [clockSynced] @returns {void} */
function renderAgenda(events, calendarOk = true, clockSynced = true) {
  // Today always leads, so it can render "Nothing today" even with no events.
  const groups = withTodayGroup(groupByDay(events), localDayKey());
  const [col1, col2] = splitColumns(groups);
  const root = document.getElementById("agenda-body");
  if (!root) return;
  root.replaceChildren();
  // Fit measures the natural-height body, not the tile: the tile is a stretched
  // grid item, so rowH(tile) would always equal the budget and never trim.
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
  // After layout, so measured heights are real.
  const budget = root.clientHeight;
  if (budget > 0) for (const body of bodies) fitColumnInPlace(body, budget);
}

// ── status + manual refresh ──────────────────────────────────────────────────

// In-flight manual refresh: blocks a double-tap and survives renderStatus rebuilds
// as the source of truth for the spin state.
let refreshing = false;

// Latest from renderStatus opts, so the stable click handler calls the current one.
/** @type {(() => Promise<void>) | null} */
let coreRefresh = null;

// Re-query: the node is replaced on every repaint.
/** @param {boolean} on @returns {void} */
function setRefreshSpinning(on) {
  const r = document.querySelector("#status .refresh");
  if (r) r.classList.toggle("is-spinning", on);
}

// A kiosk has no visible console, so a failed refresh flashes red instead.
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

/** @returns {Promise<void>} */
async function onRefresh() {
  if (refreshing) return;
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

// Built once per mount and re-inserted on every footer rebuild.
/** @type {HTMLElement} */
let adminCog;

/** @returns {HTMLElement} */
function cogNode() {
  const cog = el("button", "admin-cog");
  cog.setAttribute("type", "button");
  cog.setAttribute("title", "Admin");
  cog.setAttribute("aria-label", "Admin");
  cog.innerHTML = SETTINGS_SVG; // trusted own SVG markup only
  cog.addEventListener("click", () => go("admin")); // tap → click (synthesized from wl_touch)
  return cog;
}

/** @param {string} label @param {boolean} ok @returns {HTMLElement} */
function srcNode(label, ok) {
  const item = el("span", "st-item" + (ok ? "" : " stale"));
  item.append(el("span", "st-sq" + (ok ? "" : " stale")), `${label} ${ok ? "ok" : "stale"}`);
  return item;
}

// `opts.stale` (fetch failed) forces an all-stale "Updated —" row so the kiosk
// degrades visibly.
/** @param {DashboardDoc | null} data @param {StatusOpts} [opts] @returns {void} */
function renderStatus(data, opts = {}) {
  coreRefresh = opts.refresh ?? null;
  /** @type {[string, WeatherBlock | CalendarBlock | null][]} */
  const sources = [
    ["Weather", data && data.weather],
    ["Calendar", data && data.calendar],
  ];

  // Oldest fetched_at among OK sources, so the stamp can't over-claim freshness;
  // shown in the stamp's local wall-clock time, not the Pi clock's.
  const chosen = opts.stale ? null : pickUpdated(sources.map(([, s]) => s));
  // fetched_at is always a datetime, but guard a null time like sunrise/sunset do.
  const time = chosen ? localParts(chosen).time : null;
  const updated = time ? fmtLong(time) : "—";

  const status = document.getElementById("status");
  if (!status) return;
  status.replaceChildren(adminCog);
  for (const [label, s] of sources)
    status.append(srcNode(label, Boolean(!opts.stale && s && s.ok)));
  status.append(el("span", "st-updated", `Updated ${updated}`));

  const refresh = el("button", "refresh");
  refresh.setAttribute("type", "button");
  refresh.setAttribute("title", "refresh");
  refresh.innerHTML = REFRESH_SVG; // trusted own SVG only
  refresh.append("Refresh");
  // This node is rebuilt every poll; re-derive the spin so a mid-refresh repaint keeps it.
  if (refreshing) refresh.classList.add("is-spinning");
  refresh.addEventListener("click", onRefresh); // tap → click (synthesized from wl_touch)
  status.append(refresh);
}

// Cold-boot degrade: placeholders so no grid cell is left blank.
/** @returns {void} */
function renderUnavailable() {
  const current = document.getElementById("current");
  if (current) current.replaceChildren(el("div", "cur-unavailable", "Weather unavailable"));
  const forecast = document.getElementById("forecast");
  // Spans all four columns (grid-column:1/-1).
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
