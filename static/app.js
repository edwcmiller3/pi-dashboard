// Pi Dashboard front-end — vanilla, functional render of the data contract.
//
// Phase 2: reads a static ./data.json fixture. In Phase 3 the single DATA_URL
// constant flips to the live JSON API ("/api/data" or similar) with no other
// change — every render function below already consumes the final contract.
//
// Time policy: event/sunrise/sunset times are rendered from the wall-clock
// encoded in each ISO string's local part (honoring "render from the API
// offset, not the Pi clock"). The big clock is the deliberate exception — it
// ticks live from the browser (clock-sync honesty is a Phase-6 concern).

const DATA_URL = "./data.json";

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
  // Federal holiday / lesser observance -> pill above the day's events.
  if (ev.kind === "holiday" || ev.kind === "observance") {
    const pill = el("span", ev.kind === "holiday" ? "holiday" : "holiday observance");
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

  // "Updated" = the LATEST fetched_at among sources that fetched OK. Pick by
  // actual instant (epoch) so mixed UTC offsets compare chronologically, then
  // render that chosen string's LOCAL wall-clock part (not the Pi clock).
  const okStamps = opts.stale
    ? []
    : sources
        .map(([, s]) => s)
        .filter((s) => s && s.ok && s.fetched_at)
        .map((s) => s.fetched_at);
  const latest = okStamps.reduce(
    (best, iso) => (best === null || Date.parse(iso) > Date.parse(best) ? iso : best),
    null,
  );
  const updated = latest ? fmtLong(localParts(latest).time) : "—";

  const status = document.getElementById("status");
  status.replaceChildren();
  for (const [label, s] of sources) status.append(srcNode(label, !opts.stale && s && s.ok));
  status.append(el("span", "sep", "·"), el("span", null, `Updated ${updated}`));

  const refresh = el("span", "refresh");
  refresh.setAttribute("title", "refresh");
  refresh.innerHTML = REFRESH_SVG; // trusted backend/own SVG markup only — never interpolate calendar/user strings here.
  status.append(refresh);
}

// ── boot ─────────────────────────────────────────────────────────────────────

async function init() {
  renderClock();
  setInterval(renderClock, 1000);
  try {
    const res = await fetch(DATA_URL, { cache: "no-store" });
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    const data = await res.json();
    renderCurrent(data.weather);
    renderForecast(data.weather.forecast);
    renderAgenda(data.calendar.events);
    renderStatus(data);
  } catch (err) {
    console.error("dashboard load failed:", err);
    // Degrade visibly: don't leave a black panel + ticking clock with no signal.
    // Both source dots go stale, "Updated —", and a glanceable notice shows.
    renderStatus(null, { stale: true });
    const agenda = document.getElementById("agenda-body");
    if (agenda) agenda.replaceChildren(el("div", "agenda-empty", "Data unavailable"));
  }
}

// Browser-only bootstrap. Guarded so importing this module under node:test
// (for the pure-function unit tests) runs no DOM/init side effects.
if (typeof document !== "undefined") init();
