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
function localParts(iso) {
  const t = iso.indexOf("T");
  if (t === -1) return { date: iso, time: null };
  return {
    date: iso.slice(0, t),
    time: { hh: +iso.slice(t + 1, t + 3), mm: +iso.slice(t + 4, t + 6) },
  };
}

function to12(hh) {
  const ampm = hh >= 12 ? "PM" : "AM";
  const h = hh % 12 || 12;
  return { h, ampm };
}

const pad2 = (n) => String(n).padStart(2, "0");

// "8:30a" / "12:00p" — compact, for events and sunrise/sunset.
function fmtCompact({ hh, mm }) {
  const { h, ampm } = to12(hh);
  return `${h}:${pad2(mm)}${ampm[0].toLowerCase()}`;
}

// "9:40 AM" — for the status "Updated" stamp.
function fmtLong({ hh, mm }) {
  const { h, ampm } = to12(hh);
  return `${h}:${pad2(mm)} ${ampm}`;
}

// Parse a date-only "YYYY-MM-DD" as a LOCAL calendar date (no UTC shift).
function localDate(dateStr) {
  const [y, m, d] = dateStr.split("-").map(Number);
  return new Date(y, m - 1, d);
}

function isSameDay(a, b) {
  return (
    a.getFullYear() === b.getFullYear() &&
    a.getMonth() === b.getMonth() &&
    a.getDate() === b.getDate()
  );
}

// ── pure agenda transforms ───────────────────────────────────────────────────

// Flat, pre-sorted event list -> ordered [{date, items}] grouped by local day.
function groupByDay(events) {
  const map = new Map();
  for (const ev of events) {
    const { date } = localParts(ev.start);
    if (!map.has(date)) map.set(date, []);
    map.get(date).push(ev);
  }
  return [...map.entries()].map(([date, items]) => ({ date, items }));
}

// Rough render height of a day group (header + one line per item).
const dayWeight = (g) => 1 + g.items.length;

// Split ordered day groups into two columns, preserving chronological order
// (col 1 = earlier days, col 2 = later) while balancing total height. Both
// columns are non-empty when there are >= 2 groups.
function splitColumns(groups) {
  if (groups.length < 2) return [groups, []];
  const weights = groups.map(dayWeight);
  const total = weights.reduce((a, b) => a + b, 0);
  let acc = 0;
  let cut = 1;
  for (let i = 0; i < groups.length; i++) {
    acc += weights[i];
    if (acc * 2 >= total) {
      cut = Math.min(i + 1, groups.length - 1);
      break;
    }
  }
  return [groups.slice(0, cut), groups.slice(cut)];
}

function dayLabel(dateStr) {
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
    pill.innerHTML = STAR_SVG;
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
  document.getElementById("clock").innerHTML =
    `${h}:${pad2(now.getMinutes())}<span class="ampm">${ampm}</span>`;
  document.getElementById("date").textContent = now.toLocaleDateString(undefined, {
    weekday: "long",
    month: "long",
    day: "numeric",
  });
}

function renderCurrent(weather) {
  const c = weather.current;
  document.getElementById("current-card").innerHTML = `
    <i class="wi ${c.icon} cur-icon"></i>
    <div class="cur-main">
      <div class="cur-temp">${c.temp_f}<span class="deg">°</span></div>
      <div class="cur-cond">${c.text} <small>&middot; H ${c.high_f}° / L ${c.low_f}°</small></div>
    </div>
    <div class="cur-div"></div>
    <div class="cur-stats">
      <div class="stat"><span class="k">Feels like</span><span class="v">${c.feels_like_f}°</span></div>
      <div class="stat"><span class="k"><i class="wi wi-raindrop"></i> Rain</span><span class="v">${c.precip_prob_pct}%</span></div>
      <div class="stat"><span class="k"><i class="wi wi-strong-wind"></i> Wind</span><span class="v">${c.wind_mph} mph</span></div>
      <div class="stat"><span class="k"><i class="wi wi-humidity"></i> Humidity</span><span class="v">${c.humidity_pct}%</span></div>
      <div class="stat"><span class="k"><i class="wi wi-sunrise"></i> Sunrise</span><span class="v">${fmtCompact(localParts(c.sunrise).time)}</span></div>
      <div class="stat"><span class="k"><i class="wi wi-sunset"></i> Sunset</span><span class="v">${fmtCompact(localParts(c.sunset).time)}</span></div>
    </div>`;
}

function renderForecast(forecast) {
  const root = document.getElementById("forecast");
  root.replaceChildren();
  for (const f of forecast) {
    const dname = localDate(f.date).toLocaleDateString(undefined, { weekday: "long" });
    const card = el("section", "glass fcard");
    card.innerHTML =
      `<span class="fday">${dname}</span>` +
      `<i class="wi ${f.icon}"></i>` +
      `<span class="ftemp">${f.high_f}°<span class="lo"> / ${f.low_f}°</span></span>`;
    root.append(card);
  }
}

function renderAgenda(events) {
  const [col1, col2] = splitColumns(groupByDay(events));
  const root = document.getElementById("agenda-body");
  root.replaceChildren();
  for (const col of [col1, col2]) {
    const colEl = el("div", "agenda-col");
    for (const group of col) colEl.append(dayRowNode(group));
    root.append(colEl);
  }
}

function renderStatus(data) {
  const sources = [
    ["Weather", data.weather],
    ["Calendar", data.calendar],
  ];
  // "Updated" = earliest fetched_at among sources that fetched OK.
  const okTimes = sources
    .map(([, s]) => s)
    .filter((s) => s && s.ok && s.fetched_at)
    .map((s) => s.fetched_at)
    .sort();
  const updated = okTimes.length ? fmtLong(localParts(okTimes[0]).time) : "—";

  const dots = sources
    .map(
      ([label, s]) =>
        `<span class="src"><span class="dot ${s && s.ok ? "" : "stale"}" ` +
        `title="${label.toLowerCase()}"></span><span class="lbl">${label}</span></span>`,
    )
    .join("");

  document.getElementById("status").innerHTML =
    `${dots}<span class="sep">·</span><span>Updated ${updated}</span>` +
    `<span class="refresh" title="refresh">${REFRESH_SVG}</span>`;
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
  }
}

init();
