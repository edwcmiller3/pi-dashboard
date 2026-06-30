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
export function localParts(iso) {
  const t = iso.indexOf("T");
  if (t === -1) return { date: iso, time: null };
  return {
    date: iso.slice(0, t),
    time: { hh: +iso.slice(t + 1, t + 3), mm: +iso.slice(t + 4, t + 6) },
  };
}

export function to12(hh) {
  const ampm = hh >= 12 ? "PM" : "AM";
  const h = hh % 12 || 12;
  return { h, ampm };
}

const pad2 = (n) => String(n).padStart(2, "0");

// "8:30a" / "12:00p" — compact, for events and sunrise/sunset.
export function fmtCompact({ hh, mm }) {
  const { h, ampm } = to12(hh);
  return `${h}:${pad2(mm)}${ampm[0].toLowerCase()}`;
}

// "9:40 AM" — for the status "Updated" stamp.
export function fmtLong({ hh, mm }) {
  const { h, ampm } = to12(hh);
  return `${h}:${pad2(mm)} ${ampm}`;
}

// Parse a date-only "YYYY-MM-DD" as a LOCAL calendar date (no UTC shift).
export function localDate(dateStr) {
  const [y, m, d] = dateStr.split("-").map(Number);
  return new Date(y, m - 1, d);
}

export function isSameDay(a, b) {
  return (
    a.getFullYear() === b.getFullYear() &&
    a.getMonth() === b.getMonth() &&
    a.getDate() === b.getDate()
  );
}

// Local calendar day as "YYYY-MM-DD" — the date half of an event's local `start`,
// so it compares directly. Used to detect the midnight rollover.
export function localDayKey(d = new Date()) {
  return `${d.getFullYear()}-${pad2(d.getMonth() + 1)}-${pad2(d.getDate())}`;
}

// Whether the local calendar day has changed since `prevDay` (a localDayKey, or
// null on first run). At midnight this flips, driving a data reload so the agenda
// re-groups — "Today" moves to the new day and a holiday/event entering the
// window appears — instead of waiting for the next 15-min poll.
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
export function inBlackout(date, startHour = BLACKOUT_START_HOUR, endHour = BLACKOUT_END_HOUR) {
  if (startHour === endHour) return false;
  const h = date.getHours();
  return startHour < endHour ? h >= startHour && h < endHour : h >= startHour || h < endHour;
}

// ── pure agenda transforms ───────────────────────────────────────────────────

// Flat, pre-sorted event list -> ordered [{date, items}] grouped by local day.
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
export function splitColumns(groups) {
  if (groups.length < 2) return [groups, []];
  return [groups.slice(0, 1), groups.slice(1)];
}

// "Updated" = the OLDEST fetched_at among sources that fetched OK — so the
// stamp honestly means "every fresh source is at least this current," never
// over-claiming by showing the most-recent one. Compared by instant (epoch) so
// mixed UTC offsets order correctly. Returns the chosen ISO string, or null
// when nothing fetched OK.
export function pickUpdated(sources) {
  const stamps = sources
    .filter((s) => s && s.ok && s.fetched_at)
    .map((s) => s.fetched_at);
  return stamps.reduce(
    (best, iso) => (best === null || Date.parse(iso) < Date.parse(best) ? iso : best),
    null,
  );
}

export function dayLabel(dateStr) {
  const dt = localDate(dateStr);
  const isToday = isSameDay(dt, new Date());
  return {
    isToday,
    dname: isToday ? "Today" : dt.toLocaleDateString(undefined, { weekday: "long" }),
    ddate: dt.toLocaleDateString(undefined, { month: "short", day: "numeric" }),
  };
}

// ── inline SVGs (refresh + holiday star), matching the v4 mockup ─────────────

const STAR_SVG =
  '<svg viewBox="0 0 24 24" aria-hidden="true">' +
  '<path d="M12 2l2.6 6.3L21 9l-5 4.3L17.5 20 12 16.6 6.5 20 8 13.3 3 9l6.4-.7L12 2z"/></svg>';

const REFRESH_SVG =
  '<svg viewBox="0 0 24 24" aria-hidden="true" stroke-linecap="round" stroke-linejoin="round">' +
  '<path d="M21 12a9 9 0 1 1-2.64-6.36"/><path d="M21 3v4h-4"/></svg>';

// ── DOM builders ─────────────────────────────────────────────────────────────

function el(tag, className, text) {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text != null) node.textContent = text;
  return node;
}

function eventNode(ev) {
  // Federal holiday / lesser observance -> identical pill above the day's
  // events (no tiered visual weight — official and unofficial render the same;
  // `kind` stays distinct in the data as provenance only).
  if (ev.kind === "holiday" || ev.kind === "observance") {
    const pill = el("span", "holiday");
    pill.innerHTML = STAR_SVG; // trusted own SVG constant only — never interpolate calendar/user strings here.
    pill.append(" " + ev.title); // title as a text node — never HTML
    return pill;
  }
  // DST / informational marker -> plain muted line.
  if (ev.kind === "info") {
    return el("span", "marker", ev.title);
  }
  // Personal event -> time + title row.
  const { time } = localParts(ev.start);
  const row = el("div", "event");
  const when =
    ev.all_day || !time ? el("span", "etime allday", "All day") : el("span", "etime", fmtCompact(time));
  row.append(when, el("span", "etitle", ev.title));
  return row;
}

function dayRowNode(group) {
  const { isToday, dname, ddate } = dayLabel(group.date);
  const row = el("div", "day-row" + (isToday ? " is-today" : ""));
  const label = el("div", "day-label");
  label.append(el("span", "dname", dname), el("span", "ddate", ddate));
  const events = el("div", "day-events");
  for (const ev of group.items) events.append(eventNode(ev));
  row.append(label, events);
  return row;
}

// ── region renderers ─────────────────────────────────────────────────────────

// Surface the Pi's clock-sync honesty: the big clock ticks from the browser, so
// if the Pi clock isn't NTP-synced yet (no RTC, pre-network boot) it's wrong.
// Warn only when the backend explicitly reports clock_synced === false; an
// absent/true value (older cache, dev host) hides it.
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
function renderBlackout(now = new Date()) {
  const overlay = document.getElementById("blackout");
  if (overlay) overlay.hidden = !inBlackout(now);
}

// A weather <i class="wi wi-…"> glyph. The icon class is an OWN value (resolved
// by our backend's WMO->wi-* table), so it is safe in an attribute; human text
// (conditions, future alert/location strings) must NOT be built this way.
function wiIcon(iconClass, extra) {
  return el("i", "wi " + iconClass + (extra ? " " + extra : ""));
}

// A "stat" cell: an icon (optional) + uppercase key label + value. The label
// and value are set via textContent — never interpolated as HTML.
function statCell(iconClass, label, value) {
  const cell = el("div", "stat");
  const k = el("span", "k");
  if (iconClass) k.append(wiIcon(iconClass), " ");
  k.append(label);
  cell.append(k, el("span", "v", value));
  return cell;
}

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
    card.append(el("span", "fday", dname), wiIcon(f.icon), temp);
    root.append(card);
  }
}

// Measured render height of a node (includes padding/wrapping — the real px,
// not an item-count estimate, so the fit below can GUARANTEE no clipping).
const rowH = (node) => node.getBoundingClientRect().height;

const moreLine = (text) => el("div", "agenda-more", text);

// Trim a day-row's events in place until the whole row fits `budget` px,
// appending a "+N more" line when any events are hidden. Used for the days we
// must never drop outright (today; the first upcoming day), so a single very
// busy day is shortened rather than removed — which is what keeps col 2 from
// ever ending up empty.
function fitDayInPlace(dayRow, budget) {
  if (rowH(dayRow) <= budget) return;
  const events = dayRow.querySelector(".day-events");
  if (!events || events.children.length === 0) return;
  const more = moreLine(""); // present during measurement so its height is reserved
  events.append(more);
  let hidden = 0;
  while (rowH(dayRow) > budget && events.children.length > 1) {
    events.children[events.children.length - 2].remove(); // last real event (keep `more` last)
    hidden += 1;
  }
  if (hidden > 0) more.textContent = `+${hidden} more`;
  else more.remove();
}

// Fit a column of day-rows into `budget` px without clipping. The first day is
// protected (its events are trimmed, never the whole day); later days that
// don't fit are dropped and summarized with a "+N more days" footer.
function fitColumnInPlace(col, budget) {
  const first = col.firstElementChild;
  if (!first) return;
  fitDayInPlace(first, budget); // today / first upcoming day — protected
  if (col.children.length < 2) return; // nothing droppable
  const footer = moreLine("");
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

function renderAgenda(events) {
  const [col1, col2] = splitColumns(groupByDay(events));
  const root = document.getElementById("agenda-body");
  root.replaceChildren();
  const cols = [];
  for (const col of [col1, col2]) {
    const colEl = el("div", "agenda-col");
    for (const group of col) colEl.append(dayRowNode(group));
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
function srcNode(label, ok) {
  const src = el("span", "src");
  const dot = el("span", "dot" + (ok ? "" : " stale"));
  dot.setAttribute("title", label.toLowerCase());
  src.append(dot, el("span", "lbl", label));
  return src;
}

// `opts.stale` forces an all-stale, "Updated —" row (used when the fetch fails
// so the kiosk degrades visibly rather than showing a blank panel).
function renderStatus(data, opts = {}) {
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
    const data = await res.json();
    renderCurrent(data.weather);
    renderForecast(data.weather.forecast);
    renderAgenda(data.calendar.events);
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
