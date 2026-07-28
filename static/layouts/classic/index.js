// Classic layout - today's production UI, extracted as the first pluggable
// layout. Exports a `layout` object implementing the seven-hook Layout interface
// (see core/contract.js): mount() builds the bento-over-ambient-glow shell into
// the bare <div id="app">, and the per-region renderers fill it from the data
// contract. Every human/PII string is routed through textContent (never
// innerHTML); only own values (icon classes, the refresh SVG) touch markup.
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
/** @typedef {import("../../core/format.js").HiLoLine} HiLoLine */

// ── shell ────────────────────────────────────────────────────────────────────

// Build the classic DOM shell into the bare mount root: the five empty region
// containers (#clock/#date/#clock-warn, #current-card, #forecast, #agenda-body,
// #status) plus the one hardcoded "Upcoming" heading. The renderers below fill
// them; only the shell + that heading are static (matching the pre-refactor
// index.html exactly).
/** @param {HTMLElement} root @returns {void} */
function mount(root) {
  const screen = el("div", "screen");

  const top = el("div", "top");
  const clockCard = el("section", "glass clock-card");
  const clock = el("div", "clock");
  clock.id = "clock";
  const date = el("div", "date");
  date.id = "date";
  // Shown only while the Pi clock is NOT NTP-synced (clock_synced=false), since
  // the big clock ticks from the browser and would be wrong.
  const warn = el("div", "clock-warn", "clock not yet synced");
  warn.id = "clock-warn";
  warn.hidden = true;
  clockCard.append(clock, date, warn);
  const currentCard = el("section", "glass current-card");
  currentCard.id = "current-card";
  top.append(clockCard, currentCard);

  // Forecast = 4 FUTURE days only (today's H/L lives in the hero).
  const forecast = el("div", "forecast");
  forecast.id = "forecast";

  const agendaCard = el("section", "glass agenda-card");
  const body = el("div", "agenda-body");
  body.id = "agenda-body";
  const status = el("div", "status");
  status.id = "status";
  agendaCard.append(el("h1", null, "Upcoming"), body, status);

  screen.append(top, forecast, agendaCard);
  root.append(screen);
}

// ── inline SVG (refresh), matching the mockup ─────────────────────────────────

const REFRESH_SVG =
  '<svg viewBox="0 0 24 24" aria-hidden="true" stroke-linecap="round" stroke-linejoin="round">' +
  '<path d="M21 12a9 9 0 1 1-2.64-6.36"/><path d="M21 3v4h-4"/></svg>';

// ── DOM builders ─────────────────────────────────────────────────────────────

// `isNext` marks the "next up" event with a subtle highlight; `isPast` tags an
// already-past event `.is-past` - no CSS of its own, purely a marker the
// fitDayInPlace roll-off pass consumes. Both apply only to a personal timed
// row - the only kind nextUp/pastIndexes ever select - so the holiday/marker
// branches ignore them.
/** @param {AgendaItem} ev @param {boolean} [isNext] @param {boolean} [isPast] @returns {HTMLElement} */
function eventNode(ev, isNext = false, isPast = false) {
  // Federal holiday / lesser observance -> identical pill above the day's
  // events (no tiered visual weight - official and unofficial render the same;
  // `kind` stays distinct in the data as provenance only).
  if (ev.kind === "holiday" || ev.kind === "observance") {
    return el("span", "holiday", ev.title); // title as text (textContent) - never HTML
  }
  // DST / informational marker -> plain muted line.
  if (ev.kind === "info") {
    return el("span", "marker", ev.title);
  }
  // Personal event -> time + title row; the next-up one gets a subtle highlight
  // so the event to look at reads at a glance (no chip - the tint is enough).
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
  // "Today awareness": the next-up highlight and the roll-off candidates share
  // one gate - TODAY only, and only when the clock is trustworthy (an unsynced
  // Pi clock would mis-pick both; undefined/true = fine) - and one `now`, so
  // the emphasized row can never simultaneously be a roll-off candidate.
  const aware = isToday && clockSynced !== false;
  const now = new Date();
  const nextIdx = aware ? nextUp(group.items, now) : -1;
  const pastIdx = new Set(aware ? pastIndexes(group.items, now) : []);
  group.items.forEach((ev, i) => events.append(eventNode(ev, i === nextIdx, pastIdx.has(i))));
  // Quiet-day state: today with no personal events gets a friendly "Nothing
  // today" (holidays/observances above still show as context). Only when the
  // calendar fetched OK - on a stale/failed calendar we don't know today's
  // events, so we don't claim emptiness (the stale status dot signals it).
  if (isToday && calendarOk && !hasPersonalEvents(group.items)) {
    events.append(el("div", "day-empty", "Nothing today"));
  }
  row.append(label, events);
  return row;
}

// A weather <i class="wi wi-…"> glyph. The icon class is an OWN value (resolved
// by our backend's WMO->wi-* table), so it is safe in an attribute; human text
// (conditions, future alert/location strings) must NOT be built this way.
/** @param {string} iconClass @param {string} [extra] @returns {HTMLElement} */
function wiIcon(iconClass, extra) {
  return el("i", "wi " + iconClass + (extra ? " " + extra : ""));
}

// A "stat" cell: an icon (optional) + uppercase key label + value. The label
// and value are set via textContent - never interpolated as HTML.
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

// One glyph+value line of a fmtHiLo pair (hero stack and forecast cards);
// the glyph gets its own span so CSS can size/color it independently.
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

// Live wall-clock from the browser (the one time source NOT taken from the API),
// plus the clock-sync warning. `synced` false -> show the warning (Pi clock not
// NTP-synced yet); true/unknown -> hide it.
/** @param {Date} now @param {boolean} synced @returns {void} */
function renderClock(now, synced) {
  const { h, ampm } = to12(now.getHours());
  // h/minutes are own numbers; build via el()/textContent so no human/contract
  // text is ever interpolated into markup here.
  const clock = document.getElementById("clock");
  if (clock) clock.replaceChildren(`${h}:${pad2(now.getMinutes())}`, el("span", "ampm", ampm));
  const date = document.getElementById("date");
  if (date) date.textContent = now.toLocaleDateString(undefined, {
    weekday: "long",
    month: "long",
    day: "numeric",
  });
  // Guard the write: the core drives renderClock every second, but the sync
  // state changes rarely, so only touch #clock-warn.hidden when it actually
  // flips (a plain idempotent write would repaint-poke the node each tick).
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
  // c.text is HUMAN TEXT - route through textContent, never innerHTML.
  cond.append(c.text);
  main.append(tempRow, cond);

  const stats = el("div", "cur-stats");
  stats.append(
    statCell(null, "Feels like", `${c.feels_like_f}°`),
    statCell("wi-raindrop", "Rain", `${c.precip_prob_pct}%`),
    statCell("wi-strong-wind", "Wind", `${c.wind_mph} mph`),
    statCell("wi-humidity", "Humidity", `${c.humidity_pct}%`),
    statCell("wi-sunrise", "Sunrise", fmtCompactOr(localParts(c.sunrise).time)),
    statCell("wi-sunset", "Sunset", fmtCompactOr(localParts(c.sunset).time)),
  );

  card.append(wiIcon(c.icon, "cur-icon"), main, el("div", "cur-div"), stats);
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
    const card = el("section", "glass fcard");

    const temp = el("span", "ftemp");
    const { hi, lo } = fmtHiLo(f);
    temp.append(hiLoLine("hi", hi), hiLoLine("lo", lo));

    // Right of the icon: temps, with the precip-chance line beneath - shown only
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

// ── agenda fit shells (DOM around the pure planners) ──────────────────────────

// Measured render height of a node (includes padding/wrapping - the real px,
// not an item-count estimate, so the fit below can GUARANTEE no clipping).
/** @param {Element} node @returns {number} */
const rowH = (node) => node.getBoundingClientRect().height;

/** @param {string} text @returns {HTMLElement} */
const moreLine = (text) => el("div", "agenda-more", text);

// Height a "+N …" summary line will occupy in `container`, measured with a real
// (briefly attached) placeholder - an estimate could under-reserve and let the
// final label push a "fitting" row back over budget. Any one-line text measures
// the same, so "+0 more" stands in for every label the planners charge for.
/** @param {Element} container @returns {number} */
function measureLine(container) {
  const probe = moreLine("+0 more");
  container.append(probe);
  const h = rowH(probe);
  probe.remove();
  return h;
}

// Trim a day-row's events in place until the whole row fits `budget` px -
// the imperative shell around the pure `planDayFit` (see its contract for the
// roll-off/trim semantics). Used for the days we must never drop outright
// (today; the first upcoming day), so a single very busy day is shortened
// rather than removed - which is what keeps col 2 from ever ending up empty.
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
    // Takes the oldest past row's place - below the all-day/holiday pills,
    // right where the timed list begins.
    const firstPast = children.find((c) => c.classList.contains("is-past"));
    if (firstPast) firstPast.before(moreLine(`+${plan.earlierCount} earlier`));
  }
  for (const i of plan.hide) children[i].remove();
  if (plan.moreCount > 0) events.append(moreLine(`+${plan.moreCount} more`));
}

// Fit a column of day-rows into `budget` px without clipping - the imperative
// shell around the pure `planColumnFit`. The first day is protected (its events
// are trimmed via fitDayInPlace, never the whole day); later days that don't
// fit are dropped and summarized with a "+N more days" footer.
/** @param {Element} col @param {number} budget @returns {void} */
function fitColumnInPlace(col, budget) {
  const first = col.firstElementChild;
  if (!first) return;
  fitDayInPlace(first, budget); // today / first upcoming day - protected
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
  // Guarantee today leads so column 1 always shows today (and can render the
  // quiet-day "Nothing today" when today has no events at all).
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
  // Measure-and-fit pass (after layout, so heights are real): neither column
  // may clip. col 1 = today (events trimmed if needed); col 2 = upcoming days,
  // first one protected, the rest summarized as "+N more days".
  const budget = root.clientHeight;
  if (budget > 0) for (const colEl of cols) fitColumnInPlace(colEl, budget);
}

// ── status + manual refresh ──────────────────────────────────────────────────

// True while a manual POST /refresh is in flight. Guards against a double-tap (or
// a poll-driven repaint) starting a second concurrent refresh, and is the source
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
  status.append(el("span", "sep", "·"), el("span", null, `Updated ${updated}`));

  const refresh = el("span", "refresh");
  refresh.setAttribute("title", "refresh");
  refresh.setAttribute("role", "button");
  refresh.innerHTML = REFRESH_SVG; // trusted backend/own SVG markup only - never interpolate calendar/user strings here.
  // Reflect an in-flight manual refresh: renderStatus rebuilds this node on every
  // poll, so the spin can't live only on the old node - re-derive it from the
  // module flag each render so a repaint mid-refresh keeps spinning.
  if (refreshing) refresh.classList.add("is-spinning");
  refresh.addEventListener("click", onRefresh); // tap → click (Chromium synthesizes it from wl_touch even with mouseEmulation="no")
  status.append(refresh);
}

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
