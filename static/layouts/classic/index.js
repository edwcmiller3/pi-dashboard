// Classic layout (bento over ambient glow), implementing the Layout contract
// (core/contract.js). Human/PII strings go through textContent only; just own
// values (icon classes, the refresh SVG) touch markup.
//
// Side-effect-free on import (see core/machine.js): the DOM is touched only in
// mount() and the render hooks.

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
/** @typedef {import("../../core/format.js").HiLoLine} HiLoLine */
/** @typedef {import("../../core/contract.js").IconPack} IconPack */
/** @typedef {import("../../core/contract.js").GlyphName} GlyphName */

// Injected at mount; every glyph routes through it so this layout never names a pack.
/** @type {IconPack} */
let iconPack;

// ── shell ────────────────────────────────────────────────────────────────────

/** @param {HTMLElement} root @param {{ icon: IconPack }} ctx @returns {void} */
function mount(root, ctx) {
  iconPack = ctx.icon;
  const screen = el("div", "screen");

  const top = el("div", "top");
  const clockCard = el("section", "glass clock-card");
  const clock = el("div", "clock");
  clock.id = "clock";
  const date = el("div", "date");
  date.id = "date";
  // Shown while the Pi clock isn't NTP-synced: the clock ticks from the browser.
  const warn = el("div", "clock-warn", "clock not yet synced");
  warn.id = "clock-warn";
  warn.hidden = true;
  clockCard.append(clock, date, warn);
  const currentCard = el("section", "glass current-card");
  currentCard.id = "current-card";
  top.append(clockCard, currentCard);

  // Future days only - today's H/L lives in the hero.
  const forecast = el("div", "forecast");
  forecast.id = "forecast";

  const agendaCard = el("section", "glass agenda-card");
  const body = el("div", "agenda-body");
  body.id = "agenda-body";
  const status = el("div", "status");
  status.id = "status";
  // Sibling of #status (not inside it) so renderStatus repaints never drop it.
  const cog = el("button", "admin-cog");
  cog.setAttribute("type", "button");
  cog.setAttribute("title", "Admin");
  cog.setAttribute("aria-label", "Admin");
  cog.innerHTML = SETTINGS_SVG; // trusted own SVG markup only
  cog.addEventListener("click", () => go("admin")); // tap → click (synthesized from wl_touch)
  agendaCard.append(el("h1", null, "Upcoming"), body, cog, status);

  screen.append(top, forecast, agendaCard);
  root.append(screen);
}

// ── inline SVG (refresh) ─────────────────────────────────────────────────────

const REFRESH_SVG =
  '<svg viewBox="0 0 24 24" aria-hidden="true" stroke-linecap="round" stroke-linejoin="round">' +
  '<path d="M21 12a9 9 0 1 1-2.64-6.36"/><path d="M21 3v4h-4"/></svg>';

// ── DOM builders ─────────────────────────────────────────────────────────────

// `.is-past` has no CSS; it's a marker for the fitDayInPlace roll-off pass. Both
// flags only ever select personal timed rows, so holiday/marker branches ignore them.
/** @param {AgendaItem} ev @param {boolean} [isNext] @param {boolean} [isPast] @returns {HTMLElement} */
function eventNode(ev, isNext = false, isPast = false) {
  // Holidays and observances render identically; `kind` is provenance only.
  if (ev.kind === "holiday" || ev.kind === "observance") {
    return el("span", "holiday", ev.title); // title as text (textContent) - never HTML
  }
  if (ev.kind === "info") {
    return el("span", "marker", ev.title);
  }
  const { time } = localParts(ev.start);
  const row = el("div", "event" + (isNext ? " is-next" : "") + (isPast ? " is-past" : ""));
  const when =
    ev.all_day || !time ? el("span", "etime allday", "All day") : el("span", "etime", fmtCompact(time));
  row.append(when, el("span", "etitle", ev.title)); // title as text (textContent) - never HTML
  return row;
}

/** @param {DayGroup} group @param {boolean} [calendarOk] @param {boolean} [clockSynced] @returns {HTMLElement} */
function dayRowNode(group, calendarOk = true, clockSynced = true) {
  const { isToday, dname, ddate } = dayLabel(group.date);
  const row = el("div", "day-row" + (isToday ? " is-today" : ""));
  const label = el("div", "day-label");
  label.append(el("span", "dname", dname), el("span", "ddate", ddate));
  const events = el("div", "day-events");
  // Next-up and roll-off share one gate (today, trusted clock) and one `now`, so
  // the highlighted row can never also be a roll-off candidate.
  const aware = isToday && clockSynced !== false;
  const now = new Date();
  const nextIdx = aware ? nextUp(group.items, now) : -1;
  const pastIdx = new Set(aware ? pastIndexes(group.items, now) : []);
  group.items.forEach((ev, i) => events.append(eventNode(ev, i === nextIdx, pastIdx.has(i))));
  // Only claim emptiness when the calendar fetched OK - a stale feed doesn't know.
  if (isToday && calendarOk && !hasPersonalEvents(group.items)) {
    events.append(el("div", "day-empty", "Nothing today"));
  }
  row.append(label, events);
  return row;
}

/**
 * @param {GlyphName | null} glyph
 * @param {string} label
 * @param {string} value
 * @returns {HTMLElement}
 */
function statCell(glyph, label, value) {
  const cell = el("div", "stat");
  const k = el("span", "k");
  if (glyph) k.append(iconPack.renderIcon(glyph), " ");
  k.append(label);
  cell.append(k, el("span", "v", value));
  return cell;
}

// The glyph gets its own span so CSS can size/color it independently.
/**
 * @param {"hi" | "lo"} cls
 * @param {HiLoLine} line
 * @returns {HTMLElement}
 */
function hiLoLine(cls, line) {
  const node = el("span", cls);
  node.append(el("span", "glyph", line.glyph), line.temp);
  return node;
}

// ── region renderers ─────────────────────────────────────────────────────────

// The browser clock is the one time source not taken from the API.
/** @param {Date} now @param {boolean} synced @returns {void} */
function renderClock(now, synced) {
  const { h, ampm } = to12(now.getHours());
  const clock = document.getElementById("clock");
  if (clock) clock.replaceChildren(`${h}:${pad2(now.getMinutes())}`, el("span", "ampm", ampm));
  const date = document.getElementById("date");
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
  const card = document.getElementById("current-card");
  if (!card) return;
  card.replaceChildren();

  const main = el("div", "cur-main");
  const temp = el("div", "cur-temp");
  temp.append(String(c.temp_f), el("span", "deg", "°"));
  const { hi, lo } = fmtHiLo(c);
  const hilo = el("div", "cur-hilo");
  hilo.append(hiLoLine("hi", hi), hiLoLine("lo", lo));
  const tempRow = el("div", "cur-temp-row");
  tempRow.append(temp, hilo);
  const cond = el("div", "cur-cond");
  cond.append(c.text); // human text - textContent only
  main.append(tempRow, cond);

  const stats = el("div", "cur-stats");
  stats.append(
    statCell(null, "Feels like", `${c.feels_like_f}°`),
    statCell("precip", "Rain", `${c.precip_prob_pct}%`),
    statCell("wind", "Wind", `${c.wind_mph} mph`),
    statCell("humidity", "Humidity", `${c.humidity_pct}%`),
    statCell("sunrise", "Sunrise", fmtCompactOr(localParts(c.sunrise).time)),
    statCell("sunset", "Sunset", fmtCompactOr(localParts(c.sunset).time)),
  );

  card.append(iconPack.renderIcon(c.icon, "cur-icon"), main, el("div", "cur-div"), stats);
}

/** @param {ForecastDay[]} forecast @returns {void} */
function renderForecast(forecast) {
  const root = document.getElementById("forecast");
  if (!root) return;
  root.replaceChildren();
  // The grid is a fixed repeat(4,1fr); slice so a long feed can't misalign it.
  for (const f of forecast.slice(0, 4)) {
    const dname = localDate(f.date).toLocaleDateString(undefined, { weekday: "long" });
    const card = el("section", "glass fcard");

    const temp = el("span", "ftemp");
    const { hi, lo } = fmtHiLo(f);
    temp.append(hiLoLine("hi", hi), hiLoLine("lo", lo));

    // Precip line only on wet codes (backend is_wet gate); absent flag = dry.
    const right = el("div", "fright");
    right.append(temp);
    if (f.precip_expected) {
      const precip = el("div", "fprecip");
      precip.append(iconPack.renderIcon("precip"), el("span", null, `${f.precip_prob_pct}%`));
      right.append(precip);
    }

    const mid = el("div", "fmid");
    mid.append(iconPack.renderIcon(f.icon, "fcard-icon"), right);

    card.append(el("span", "fday", dname), mid, el("span", "fdesc", f.text));
    root.append(card);
  }
}

// ── agenda fit shells (DOM around the pure planners) ──────────────────────────

// Real measured px (not an item-count estimate), so the fit can guarantee no clipping.
/** @param {Element} node @returns {number} */
const rowH = (node) => node.getBoundingClientRect().height;

/** @param {string} text @returns {HTMLElement} */
const moreLine = (text) => el("div", "agenda-more", text);

// Measured with a briefly attached probe - an estimate could under-reserve and let
// the final label push a fitting row over budget. Any one-line text measures the
// same, so "+0 more" stands in for every label.
/** @param {Element} container @returns {number} */
function measureLine(container) {
  const probe = moreLine("+0 more");
  container.append(probe);
  const h = rowH(probe);
  probe.remove();
  return h;
}

// DOM shell around the pure planDayFit. For days never dropped outright (today,
// first upcoming day): a busy day is shortened, which keeps col 2 from going empty.
/** @param {Element} dayRow @param {number} budget @returns {void} */
function fitDayInPlace(dayRow, budget) {
  const events = dayRow.querySelector(".day-events");
  if (!events || events.children.length === 0) return;
  const children = [...events.children];
  const plan = planDayFit(
    rowH(dayRow),
    children.map(rowH),
    children.map((c) => c.classList.contains("is-past")),
    measureLine(events),
    budget,
  );
  if (plan.earlierCount > 0) {
    // In the oldest past row's place - below the pills, where the timed list begins.
    const firstPast = children.find((c) => c.classList.contains("is-past"));
    if (firstPast) firstPast.before(moreLine(`+${plan.earlierCount} earlier`));
  }
  for (const i of plan.hide) children[i].remove();
  if (plan.moreCount > 0) events.append(moreLine(`+${plan.moreCount} more`));
}

// DOM shell around the pure planColumnFit. The first day is trimmed, never
// dropped; later days that don't fit collapse into a "+N more days" footer.
/** @param {Element} col @param {number} budget @returns {void} */
function fitColumnInPlace(col, budget) {
  const first = col.firstElementChild;
  if (!first) return;
  fitDayInPlace(first, budget);
  const days = [...col.children];
  const plan = planColumnFit(rowH(col), days.map(rowH), measureLine(col), budget);
  for (let k = 0; k < plan.dropCount; k++) days[days.length - 1 - k].remove();
  if (plan.showFooter) {
    const n = plan.dropCount;
    col.append(moreLine(`+${n} more day${n === 1 ? "" : "s"}`));
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
  const cols = [];
  for (const col of [col1, col2]) {
    const colEl = el("div", "agenda-col");
    for (const group of col) colEl.append(dayRowNode(group, calendarOk, clockSynced));
    root.append(colEl);
    cols.push(colEl);
  }
  // After layout, so measured heights are real.
  const budget = root.clientHeight;
  if (budget > 0) for (const colEl of cols) fitColumnInPlace(colEl, budget);
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
function flashRefreshError() {
  const r = document.querySelector("#status .refresh");
  if (!r) return;
  r.classList.add("is-error");
  setTimeout(() => {
    const cur = document.querySelector("#status .refresh");
    if (cur) cur.classList.remove("is-error");
  }, 1500);
}

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

/** @param {string} label @param {boolean} ok @returns {HTMLElement} */
function srcNode(label, ok) {
  const src = el("span", "src");
  const dot = el("span", "dot" + (ok ? "" : " stale"));
  dot.setAttribute("title", label.toLowerCase());
  src.append(dot, el("span", "lbl", label));
  return src;
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
  status.replaceChildren();
  for (const [label, s] of sources)
    status.append(srcNode(label, Boolean(!opts.stale && s && s.ok)));
  status.append(el("span", "sep", "·"), el("span", null, `Updated ${updated}`));

  const refresh = el("span", "refresh");
  refresh.setAttribute("title", "refresh");
  refresh.setAttribute("role", "button");
  refresh.innerHTML = REFRESH_SVG; // trusted own SVG only
  // This node is rebuilt every poll; re-derive the spin so a mid-refresh repaint keeps it.
  if (refreshing) refresh.classList.add("is-spinning");
  refresh.addEventListener("click", onRefresh); // tap → click (Chromium synthesizes it from wl_touch even with mouseEmulation="no")
  status.append(refresh);
}

// Cold-boot degrade: placeholders so no region is a blank glass box.
function renderUnavailable() {
  const current = document.getElementById("current-card");
  if (current) current.replaceChildren(el("div", "cur-unavailable", "Weather unavailable"));
  const forecast = document.getElementById("forecast");
  if (forecast) forecast.replaceChildren();
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
