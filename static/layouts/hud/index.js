// HUD layout (phosphor-CRT instrument panel), implementing the Layout contract
// (core/contract.js). The instruments' math lives in the pure ./geometry/
// modules; this file only turns their specs into nodes.
//
// SVG colors live in classes (layout.css), never inline, so a hue theme can
// retint via the cascade.
//
// Side-effect-free on import (see core/machine.js).

import { to12, pad2, fmtCompact, localParts, localDate, localDayKey, dayLabel } from "../../core/time.js";
import {
  groupByDay,
  withTodayGroup,
  nextUp,
  pastIndexes,
  planDayFit,
  planColumnFit,
} from "../../core/agenda.js";
import { pickUpdated } from "../../core/format.js";
import { el } from "../../core/dom.js";
import { go } from "../../core/router.js";
import { SETTINGS_SVG } from "../../core/chrome.js";
import { computeScaleWindow } from "./geometry/scale.js";
import { dialGeometry } from "./geometry/dial.js";
import { solarGeometry } from "./geometry/solar.js";
import { forecastRangePlot, forecastRuler, rulerDivisions } from "./geometry/forecast.js";

/** @typedef {import("../../core/contract.js").AgendaItem} AgendaItem */
/** @typedef {import("../../core/contract.js").WeatherBlock} WeatherBlock */
/** @typedef {import("../../core/contract.js").CalendarBlock} CalendarBlock */
/** @typedef {import("../../core/contract.js").CurrentWeather} CurrentWeather */
/** @typedef {import("../../core/contract.js").ForecastDay} ForecastDay */
/** @typedef {import("../../core/contract.js").DashboardDoc} DashboardDoc */
/** @typedef {import("../../core/contract.js").StatusOpts} StatusOpts */
/** @typedef {import("../../core/agenda.js").DayGroup} DayGroup */
/** @typedef {import("./geometry/scale.js").ScaleWindow} ScaleWindow */
/** @typedef {import("./geometry/solar.js").SolarGeometry} SolarGeometry */
/** @typedef {import("../../core/contract.js").IconPack} IconPack */

const SVG_NS = "http://www.w3.org/2000/svg";

// Injected at mount; forecast glyphs route through it so the HUD never names a pack.
/** @type {IconPack} */
let iconPack;

// ── small builders ─────────────────────────────────────────────────────────

/** @param {string} id @returns {HTMLElement | null} */
const byId = (id) => document.getElementById(id);

// Attributes are geometry only - colors come from classes (see header).
/**
 * @param {string} name
 * @param {Record<string, string | number>} [attrs]
 * @param {string} [text]
 * @returns {SVGElement}
 */
function svg(name, attrs = {}, text) {
  const node = document.createElementNS(SVG_NS, name);
  for (const [k, v] of Object.entries(attrs)) node.setAttribute(k, String(v));
  if (text != null) node.textContent = text;
  return /** @type {SVGElement} */ (node);
}

// ── geometric marks as inline SVG, not font glyphs ───────────────────────────
// ◆ ▸ ◂ ▲ ▼ ⟳ are absent from the vendored mono subset (vendor/fonts/
// subset-manifest.txt); as text they'd fall back to a system font on the Pi.

/** @param {string} cls @param {string} points @returns {SVGElement} */
function poly(cls, points) {
  const s = svg("svg", { viewBox: "0 0 10 10", class: "sym " + cls, "aria-hidden": "true" });
  s.append(svg("polygon", { points }));
  return s;
}
/** ◆ diamond bullet (holiday pill) @returns {SVGElement} */
const symDiamond = () => poly("sym-diamond", "5,0 10,5 5,10 0,5");
/** ▸ right triangle ("+N …" summary lines) @returns {SVGElement} */
const symRight = () => poly("sym-right", "1,0 9,5 1,10");
/** ◂ left triangle (ACTIVE tag) @returns {SVGElement} */
const symLeft = () => poly("sym-left", "9,0 1,5 9,10");

// ⟳ RESYNC - the classic layout's refresh arc.
/** @returns {SVGElement} */
function symResync() {
  const s = svg("svg", {
    viewBox: "0 0 24 24",
    class: "sym sym-resync",
    "aria-hidden": "true",
    "stroke-linecap": "round",
    "stroke-linejoin": "round",
  });
  s.append(svg("path", { d: "M21 12a9 9 0 1 1-2.64-6.36" }), svg("path", { d: "M21 3v4h-4" }));
  return s;
}

// ── shell (mount) ────────────────────────────────────────────────────────────

/** @param {HTMLElement} root @param {{ icon: IconPack }} ctx @returns {void} */
function mount(root, ctx) {
  iconPack = ctx.icon;
  // A remount must never read a window left over from a previous cycle.
  scaleWindow = null;

  const screen = el("div", "screen hud");

  // corner-bracket instrument frame
  /** @param {string} id @param {string} label @param {string} [extra] @returns {HTMLElement} */
  const panel = (id, label, extra) => {
    const p = el("div", "brk" + (extra ? " " + extra : ""));
    p.id = id;
    p.append(el("span", "c2"), el("span", "mlabel", label));
    return p;
  };

  // ── header : master chronometer ──
  const header = el("header", "hud-header");
  const hrow = el("div", "hrow");
  const clock = el("span", "clock glow");
  clock.id = "clock";
  const ampm = el("span", "ampm");
  ampm.id = "ampm";
  const hdate = el("span", "hdate");
  hdate.id = "hdate";
  const hmeta = el("div", "hmeta");
  const meta = el("div");
  const mode = el("b", null, "DAY");
  mode.id = "mode";
  meta.append("MODE ", mode, " · UNITS ", el("b", null, "°F / MPH"));
  hmeta.append(meta);
  hrow.append(clock, ampm, el("span", "hdiv"), hdate, hmeta);
  const warn = el("div", "clock-warn", "clock not yet synced");
  warn.id = "clock-warn";
  warn.hidden = true;
  header.append(hrow, warn, el("span", "fticks"));

  // ── main : weather stack + agenda ──
  const main = el("main", "hud-main");
  const wx = el("section", "wx");

  // primary instrument: temp dial + docked readouts
  const gauge = panel("gauge", "PRIMARY · AIR TEMP");
  const scaleLbl = el("span", "mlabel mlabel-r");
  scaleLbl.id = "scaleLbl";
  const gsvg = svg("svg", { id: "gsvg", viewBox: "0 0 580 296", preserveAspectRatio: "xMidYMid meet" });
  /** @param {string} side @param {string} vpos @param {string} dl @param {string} vid @param {string} [ds] @returns {HTMLElement} */
  const dock = (side, vpos, dl, vid, ds) => {
    const d = el("div", `dock dock-${side} dock-${vpos}`);
    const v = el("span", "dv glow");
    v.id = vid;
    d.append(el("span", "dl", dl), v);
    if (ds) d.append(el("span", "ds", ds));
    return d;
  };
  gauge.append(
    scaleLbl,
    gsvg,
    dock("l", "t", "FEELS", "d-feels"),
    dock("l", "b", "HUM", "d-hum"),
    dock("r", "t", "RAIN", "d-rain", "PRECIP PROB"),
    dock("r", "b", "WIND", "d-wind"),
  );

  // solar linear day-progress tape
  const solar = panel("solar", "SOLAR TRACK");
  solar.append(svg("svg", { id: "ssvg", viewBox: "0 0 552 47" }));

  // 4-day forecast : channel rows on the shared data-driven scale
  const fcst = panel("fcst", "FORECAST · 4 DAY");
  const fruler = el("div", "fruler");
  const rul = el("div", "rul");
  rul.id = "rul";
  fruler.append(rul);
  const frows = el("div", "frows");
  frows.id = "frows";
  fcst.append(fruler, frows);

  wx.append(gauge, solar, fcst);

  // agenda manifest
  const agenda = panel("agenda", "UPCOMING");
  const arows = el("div", "arows");
  arows.id = "agenda-body";
  agenda.append(arows);

  main.append(wx, agenda);

  // ── footer : system status ──
  const footer = el("footer", "hud-footer");
  footer.id = "status";
  adminCog = cogNode();
  footer.append(adminCog, el("span", "fticks"));

  screen.append(header, main, footer);
  // CRT dressing (scanlines + vignette): one static overlay keeps it cheap
  screen.append(el("div", "fx"));
  root.append(screen);
}

// ── clock ──────────────────────────────────────────────────────────────────

// Browser clock (the one time source not from the API); hour zero-padded.
/** @param {Date} now @param {boolean} synced @returns {void} */
function renderClock(now, synced) {
  const { h, ampm } = to12(now.getHours());
  const clock = byId("clock");
  if (clock) clock.textContent = `${pad2(h)}:${pad2(now.getMinutes())}`;
  const am = byId("ampm");
  if (am) am.textContent = ampm;
  const date = byId("hdate");
  if (date) {
    date.textContent = now
      .toLocaleDateString(undefined, { weekday: "long", month: "long", day: "numeric" })
      .toUpperCase();
  }
  const warn = byId("clock-warn");
  if (warn) warn.hidden = synced;
}

// ── current : dial + docks + solar tape ──────────────────────────────────────

// One temperature window shared by the dial and the forecast plot. Computed in
// renderCurrent (which sees the whole weather block, forecast included); relies
// on core/machine.js calling renderCurrent before renderForecast.
/** @type {ScaleWindow | null} */
let scaleWindow = null;

/** @param {string} id @param {number} value @param {string} [unit] @returns {void} */
function setDock(id, value, unit) {
  const n = byId(id);
  if (!n) return;
  n.replaceChildren(String(value));
  if (unit) n.append(el("small", null, unit));
}

// Local minutes-of-day, or null for a date-only/malformed stamp (the tape then
// hides its sunrise/sunset bugs).
/** @param {string} iso @returns {number | null} */
function isoMinutes(iso) {
  const { time } = localParts(iso);
  return time ? time.hh * 60 + time.mm : null;
}

/** "5:47a" → "5:47A" @param {number} min @returns {string} */
const clockAt = (min) => fmtCompact({ hh: Math.floor(min / 60), mm: min % 60 }).toUpperCase();

/** @param {WeatherBlock} weather @returns {void} */
function renderCurrent(weather) {
  const c = weather.current;
  // Same 4 days renderForecast plots, so extra days can't stretch the window.
  const forecast = (weather.forecast ?? []).slice(0, 4);

  /** @type {number[]} */
  const temps = [c.temp_f, c.high_f, c.low_f];
  for (const f of forecast) temps.push(f.low_f, f.high_f);
  scaleWindow = computeScaleWindow(temps);

  const scaleLbl = byId("scaleLbl");
  if (scaleLbl) scaleLbl.textContent = `SCALE ${scaleWindow.min}–${scaleWindow.max}`;
  const mode = byId("mode");
  if (mode) mode.textContent = c.is_day ? "DAY" : "NIGHT";

  setDock("d-feels", c.feels_like_f, "°");
  setDock("d-hum", c.humidity_pct, "%");
  setDock("d-rain", c.precip_prob_pct, "%");
  setDock("d-wind", c.wind_mph);

  renderDial(c, scaleWindow);
  renderSolar(c);
}

/** @param {CurrentWeather} c @param {ScaleWindow} scaleWindow @returns {void} */
function renderDial(c, scaleWindow) {
  const gsvg = byId("gsvg");
  if (!gsvg) return;
  const g = dialGeometry(c.temp_f, scaleWindow);
  const { x: cx } = g.center;
  gsvg.replaceChildren();

  gsvg.append(
    svg("path", { class: "g-arc-base", d: g.baselineArc }),
    svg("path", { class: "g-arc-glow", d: g.valueArc }),
    svg("path", { class: "g-arc-val", d: g.valueArc }),
  );
  for (const t of g.ticks) {
    gsvg.append(
      svg("line", {
        class: t.major ? "g-tick g-tick-major" : "g-tick",
        x1: t.outer.x,
        y1: t.outer.y,
        x2: t.inner.x,
        y2: t.inner.y,
      }),
    );
    if (t.label) gsvg.append(svg("text", { class: "g-num", x: t.label.x, y: t.label.y, "text-anchor": "middle" }, t.label.text));
  }
  // Center readout baselines are layout constants from the mock, not geometry.
  gsvg.append(svg("text", { class: "g-center", x: cx, y: g.center.y + 27, "text-anchor": "middle" }, `${c.temp_f}°`));
  gsvg.append(svg("text", { class: "g-cond", x: cx, y: 249, "text-anchor": "middle" }, c.text.toUpperCase()));
  const hl = svg("text", { class: "g-hl", x: cx, y: 277, "text-anchor": "middle" });
  hl.append(
    svg("tspan", { class: "g-hl-k" }, "H "),
    svg("tspan", { class: "g-hl-v" }, `${c.high_f}°`),
    svg("tspan", { class: "g-hl-k" }, " · "),
    svg("tspan", { class: "g-hl-k" }, "L "),
    svg("tspan", { class: "g-hl-v" }, `${c.low_f}°`),
  );
  gsvg.append(hl);
}

/**
 * Solar-tape marker visibility and traveled-line end. Geometry is raw (at night
 * `nowX` falls off the tape), so hide the marker off-tape and clamp the line.
 * @param {Pick<SolarGeometry, "fraction" | "nowX" | "sunriseX" | "sunsetX">} s
 * @returns {{ show: boolean, travelX: number }}
 */
export function solarMarkerDecision(s) {
  const show = s.fraction >= 0 && s.fraction <= 1;
  const travelX = Math.min(s.sunsetX, Math.max(s.sunriseX, s.nowX));
  return { show, travelX };
}

/** @param {CurrentWeather} c @returns {void} */
function renderSolar(c) {
  const ssvg = byId("ssvg");
  if (!ssvg) return;
  ssvg.replaceChildren();

  const sunriseMin = isoMinutes(c.sunrise);
  const sunsetMin = isoMinutes(c.sunset);
  if (sunriseMin === null || sunsetMin === null || sunsetMin <= sunriseMin) return;
  const now = new Date();
  const nowMin = now.getHours() * 60 + now.getMinutes();
  const s = solarGeometry({ sunriseMin, sunsetMin, nowMin });
  const { show: inDay, travelX } = solarMarkerDecision(s);

  ssvg.append(svg("line", { class: "s-baseline", x1: s.baseline.x1, y1: s.baseline.y1, x2: s.baseline.x2, y2: s.baseline.y2 }));
  for (const t of s.idleTicks) ssvg.append(svg("line", { class: "s-idle", x1: t.x1, y1: t.y1, x2: t.x2, y2: t.y2 }));

  ssvg.append(svg("line", { class: "s-travel-glow", x1: s.sunriseX, y1: s.ty, x2: travelX, y2: s.ty }));
  ssvg.append(svg("line", { class: "s-travel", x1: s.sunriseX, y1: s.ty, x2: travelX, y2: s.ty }));

  for (const b of s.bugs) ssvg.append(svg("line", { class: "s-bug", x1: b.x1, y1: b.y1, x2: b.x2, y2: b.y2 }));

  if (inDay) {
    const m = s.sunMarker;
    ssvg.append(svg("circle", { class: "s-halo", cx: m.cx, cy: m.cy, r: m.haloR }));
    ssvg.append(svg("circle", { class: "s-ring", cx: m.cx, cy: m.cy, r: m.ringR }));
    for (const t of m.crossTicks) ssvg.append(svg("line", { class: "s-cross", x1: t.x1, y1: t.y1, x2: t.x2, y2: t.y2 }));
    ssvg.append(svg("text", { class: "s-now", x: m.cx + 16, y: s.ty - 9 }, "NOW"));
  }

  // ▲▼ drawn as polygons, not glyphs (see marks above)
  const ly = 42;
  ssvg.append(svg("polygon", { class: "s-tri", points: `8,${ly} 13,${ly - 9} 3,${ly - 9}` }));
  ssvg.append(svg("text", { class: "s-label", x: 18, y: ly, "text-anchor": "start" }, `SUNRISE ${clockAt(sunriseMin)}`));
  ssvg.append(svg("text", { class: "s-label", x: 532, y: ly, "text-anchor": "end" }, `SUNSET ${clockAt(sunsetMin)}`));
  ssvg.append(svg("polygon", { class: "s-tri", points: `538,${ly - 9} 548,${ly - 9} 543,${ly}` }));
  const dh = Math.floor(s.daylightMinutes / 60);
  const dm = s.daylightMinutes % 60;
  ssvg.append(
    svg("text", { class: "s-daylight", x: (s.sunriseX + s.sunsetX) / 2, y: ly, "text-anchor": "middle" }, `DAYLIGHT ${dh}H ${pad2(dm)}M`),
  );
}

// ── forecast : range-plot channel rows ───────────────────────────────────────

/** @returns {SVGElement} */
function precipDrop() {
  const s = svg("svg", { class: "pp-drop", viewBox: "0 0 10 14", "aria-hidden": "true" });
  s.append(svg("path", { d: "M5 1 C5 1 1.6 6.4 1.6 9.2 a3.4 3.4 0 0 0 6.8 0 C8.4 6.4 5 1 5 1 Z" }));
  return s;
}

/** @param {ForecastDay[]} forecast @returns {void} */
function renderForecast(forecast) {
  const days = forecast.slice(0, 4);
  // Fallback only if renderForecast ever runs before renderCurrent.
  const plotWindow =
    scaleWindow ?? computeScaleWindow(days.flatMap((f) => [f.low_f, f.high_f]));

  // Division count goes in as a custom prop so the tick gradient (and its
  // themeable colors) stays in CSS.
  const rul = byId("rul");
  if (rul) {
    rul.replaceChildren();
    rul.style.setProperty("--divs", String(rulerDivisions(plotWindow)));
    const labels = forecastRuler(plotWindow);
    labels.forEach((lab, i) => {
      const s = el("span", null, String(lab.value));
      s.style.left = `${lab.pct}%`;
      s.style.transform = `translateX(${i === 0 ? "0" : i === labels.length - 1 ? "-100%" : "-50%"})`;
      rul.append(s);
    });
  }

  const root = byId("frows");
  if (!root) return;
  root.replaceChildren();
  const markers = forecastRangePlot(days, plotWindow);
  days.forEach((f, i) => {
    const dname = localDate(f.date).toLocaleDateString(undefined, { weekday: "short" }).toUpperCase();
    const row = el("div", "frow");

    const track = el("div", "track");
    const m = markers[i];
    const axis = el("div", "axis");
    const link = el("div", "link");
    link.style.left = `${m.linkLeftPct}%`;
    link.style.width = `${m.linkWidthPct}%`;
    const mlo = el("div", "mlo");
    mlo.style.left = `${m.loPct}%`;
    const mhi = el("div", "mhi");
    mhi.style.left = `${m.hiPct}%`;
    track.append(axis, link, mlo, mhi);

    const pp = el("div", "pp" + (f.precip_expected ? " on" : ""));
    if (f.precip_expected) pp.append(precipDrop(), el("span", null, `${f.precip_prob_pct}%`));

    row.append(
      el("span", "dn", dname),
      iconPack.renderIcon(f.icon, "gl"),
      el("span", "cond", f.text), // human text
      el("span", "lo", `${f.low_f}°`),
      track,
      el("span", "hi", `${f.high_f}°`),
      pp,
    );
    root.append(row);
  });
}

// ── agenda manifest (single column, day headers) ─────────────────────────────

// Manual walk rather than querySelector so it works on test stub nodes too.
/** @param {Element} node @param {string} cls @returns {Element | null} */
function findByClass(node, cls) {
  for (const child of node.children) {
    if (child.classList.contains(cls)) return child;
    const found = findByClass(child, cls);
    if (found) return found;
  }
  return null;
}

/** @param {Element} node @returns {number} */
const rowH = (node) => node.getBoundingClientRect().height;

/** @param {string} text @returns {HTMLElement} */
function moreLine(text) {
  const d = el("div", "more");
  d.append(symRight(), el("span", "more-t", text));
  return d;
}

/** @param {string} title @returns {HTMLElement} */
function holPill(title) {
  const p = el("span", "hol");
  p.append(symDiamond(), el("span", "hol-t", title)); // title as text - never HTML
  return p;
}

// Personal/info rows only - holidays become day-header pills. `isPast` marks a
// row for the roll-off pass.
/** @param {AgendaItem} ev @param {boolean} isActive @param {boolean} isPast @returns {HTMLElement} */
function eventNode(ev, isActive, isPast) {
  if (ev.kind === "info") {
    const row = el("div", "ev marker");
    row.append(el("span", "t"), el("span", "n", ev.title));
    return row;
  }
  const { time } = localParts(ev.start);
  const allday = ev.all_day || !time;
  const row = el("div", "ev" + (allday ? " allday" : "") + (isActive ? " active" : "") + (isPast ? " is-past" : ""));
  const t = el("span", "t", allday ? "ALL DAY" : fmtCompact(time).toUpperCase());
  row.append(t, el("span", "n", ev.title)); // title as text - never HTML
  if (isActive) {
    const tag = el("span", "atag");
    tag.append(symLeft(), el("span", "atag-t", "ACTIVE"));
    row.append(tag);
  }
  return row;
}

/** @param {DayGroup} group @param {boolean} calendarOk @param {boolean} clockSynced @returns {HTMLElement} */
function daySection(group, calendarOk, clockSynced) {
  const { isToday, dname, ddate } = dayLabel(group.date);
  const section = el("div", "dsection" + (isToday ? " is-today" : ""));

  const dhead = el("div", "dhead");
  dhead.append(el("span", "dname", isToday ? "TODAY" : dname.toUpperCase()), el("span", "ddate", ddate.toUpperCase()), el("span", "drule"));

  const pills = group.items.filter((i) => i.kind === "holiday" || i.kind === "observance");
  const rows = group.items.filter((i) => i.kind === "personal" || i.kind === "info");
  for (const p of pills) dhead.append(holPill(p.title));

  const events = el("div", "day-events");
  // One gate and one `now` for next-up and roll-off. Matched by identity because
  // nextUp/pastIndexes index the full list, not the partitioned `rows`.
  const aware = isToday && clockSynced !== false;
  const now = new Date();
  const nextIdx = aware ? nextUp(group.items, now) : -1;
  const nextEv = nextIdx >= 0 ? group.items[nextIdx] : null;
  const pastSet = new Set(aware ? pastIndexes(group.items, now).map((i) => group.items[i]) : []);
  for (const ev of rows) events.append(eventNode(ev, ev === nextEv, pastSet.has(ev)));

  // A stale/failed calendar can't claim emptiness.
  if (rows.length === 0 && calendarOk) {
    const noev = el("div", "noev");
    noev.append(el("span", "t"), el("span", "n", "— NO ENTRIES —"));
    events.append(noev);
  }
  section.append(dhead, events);
  return section;
}

// Measured with a briefly attached probe - an estimate could under-reserve. Any
// one-line label measures the same, so "+0 more" stands in.
/** @param {Element} container @returns {number} */
function measureLine(container) {
  const probe = moreLine("+0 more");
  container.append(probe);
  const h = rowH(probe);
  probe.remove();
  return h;
}

// DOM shell around the pure planDayFit; the header and pills sit outside
// .day-events, so they're never trimmed. Returns whether anything was hidden.
/** @param {Element} section @param {number} budget @returns {boolean} */
function fitDayInPlace(section, budget) {
  const events = findByClass(section, "day-events");
  if (!events || events.children.length === 0) return false;
  const children = [...events.children];
  const plan = planDayFit(
    rowH(section),
    children.map(rowH),
    children.map((c) => c.classList.contains("is-past")),
    measureLine(events),
    budget,
  );
  if (plan.earlierCount > 0) {
    const firstPast = children.find((c) => c.classList.contains("is-past"));
    if (firstPast) firstPast.before(moreLine(`+${plan.earlierCount} earlier`));
  }
  for (const i of plan.hide) children[i].remove();
  if (plan.moreCount > 0) events.append(moreLine(`+${plan.moreCount} more`));
  return plan.hide.length > 0;
}

// planColumnFit drops later days (today protected); if today alone still
// overflows, planDayFit trims it. Returns whether anything was truncated.
/** @param {Element} col @param {number} budget @returns {boolean} */
function fitColumnInPlace(col, budget) {
  const sections = [...col.children];
  if (sections.length === 0) return false;
  const footerH = measureLine(col);
  const plan = planColumnFit(rowH(col), sections.map(rowH), footerH, budget);
  for (let k = 0; k < plan.dropCount; k++) sections[sections.length - 1 - k].remove();

  // Today-trim only fires once every later day is dropped, so otherH and the
  // footer term are 0 today; kept general in case the planner contract changes.
  const kept = sections.slice(0, sections.length - plan.dropCount);
  let trimmed = false;
  if (kept.length > 0 && rowH(col) > budget) {
    const otherH = kept.slice(1).reduce((sum, s) => sum + rowH(s), 0);
    trimmed = fitDayInPlace(kept[0], budget - otherH - (plan.showFooter ? footerH : 0));
  }
  if (plan.showFooter) {
    const n = plan.dropCount;
    col.append(moreLine(`+${n} more day${n === 1 ? "" : "s"}`));
  }
  return plan.dropCount > 0 || trimmed;
}

// END OF SCHEDULE shows only when nothing was cut and the closure itself fits.
/** @param {boolean} truncated @param {boolean} hasMore @param {number} colHeight @param {number} budget @returns {boolean} */
export function showEndOfSchedule(truncated, hasMore, colHeight, budget) {
  return !truncated && !hasMore && colHeight <= budget;
}

/** @param {AgendaItem[]} events @param {boolean} [calendarOk] @param {boolean} [clockSynced] @returns {void} */
function renderAgenda(events, calendarOk = true, clockSynced = true) {
  // Today always leads, so a quiet today still shows "— NO ENTRIES —".
  const groups = withTodayGroup(groupByDay(events), localDayKey());
  const root = byId("agenda-body");
  if (!root) return;
  // root is flex-clamped (its height is the budget); `col` keeps its natural
  // content height - the real fit input - and overflows into root's clip.
  const col = el("div", "acol");
  root.replaceChildren(col);
  for (const group of groups) col.append(daySection(group, calendarOk, clockSynced));

  // After layout, so heights are real; budget 0 means not laid out (headless).
  const budget = root.clientHeight;
  if (budget > 0) {
    const truncated = fitColumnInPlace(col, budget);
    // Append first so the closure's own height counts, then keep it only if it fits.
    const hasMore = Boolean(findByClass(col, "more"));
    const eom = el("div", "eom");
    eom.append(el("span", "erule"), el("span", "eom-t", "END OF SCHEDULE"), el("span", "erule"));
    col.append(eom);
    if (!showEndOfSchedule(truncated, hasMore, rowH(col), budget)) eom.remove();
  }
}

// ── status + manual refresh ──────────────────────────────────────────────────

// Blocks a double-tap and keeps the spin across renderStatus rebuilds.
let refreshing = false;
/** @type {(() => Promise<void>) | null} */
let coreRefresh = null;

/** @param {boolean} on @returns {void} */
function setRefreshSpinning(on) {
  const r = byId("resync");
  if (r) r.classList.toggle("is-spinning", on);
}
function flashRefreshError() {
  const r = byId("resync");
  if (!r) return;
  r.classList.add("is-error");
  setTimeout(() => {
    const cur = byId("resync");
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

// Built once per mount and re-inserted on every footer rebuild.
/** @type {HTMLElement} */
let adminCog;

/** @returns {HTMLElement} */
function cogNode() {
  const cog = el("span", "admin-cog");
  cog.setAttribute("role", "button");
  cog.setAttribute("title", "Admin");
  cog.setAttribute("aria-label", "Admin");
  cog.innerHTML = SETTINGS_SVG; // trusted own SVG markup only
  cog.addEventListener("click", () => go("admin")); // tap → click (synthesized from wl_touch)
  return cog;
}

/** @param {string} label @param {boolean} ok @returns {HTMLElement} */
function okChip(label, ok) {
  return el("span", "ok" + (ok ? "" : " stale"), `${label} ${ok ? "OK" : "STALE"}`);
}

/** @param {DashboardDoc | null} data @param {StatusOpts} [opts] @returns {void} */
function renderStatus(data, opts = {}) {
  coreRefresh = opts.refresh ?? null;
  /** @type {[string, WeatherBlock | CalendarBlock | null][]} */
  const sources = [
    ["WEATHER", data && data.weather],
    ["CALENDAR", data && data.calendar],
  ];
  const chosen = opts.stale ? null : pickUpdated(sources.map(([, s]) => s));
  const time = chosen ? localParts(chosen).time : null;
  const updated = time ? fmtCompact(time).toUpperCase() : "—";

  const status = byId("status");
  if (!status) return;
  status.replaceChildren(adminCog, el("span", "fticks"));
  for (const [label, s] of sources) status.append(okChip(label, Boolean(!opts.stale && s && s.ok)));
  status.append(el("span", "upd", `UPDATED ${updated}`));

  const rfr = el("span", "rfr");
  rfr.id = "resync";
  rfr.setAttribute("role", "button");
  rfr.setAttribute("title", "manual refresh");
  rfr.append(symResync(), el("span", "rfr-t", "RESYNC"));
  if (refreshing) rfr.classList.add("is-spinning");
  rfr.addEventListener("click", onRefresh); // tap → click (synthesized from wl_touch)
  status.append(rfr);
}

// Cold-boot degrade: placeholders so no region is a blank instrument.
function renderUnavailable() {
  const gsvg = byId("gsvg");
  if (gsvg) gsvg.replaceChildren(svg("text", { class: "g-cond", x: 290, y: 150, "text-anchor": "middle" }, "WEATHER UNAVAILABLE"));
  for (const id of ["d-feels", "d-hum", "d-rain", "d-wind"]) {
    const n = byId(id);
    if (n) n.replaceChildren("—");
  }
  const ssvg = byId("ssvg");
  if (ssvg) ssvg.replaceChildren();
  const rul = byId("rul");
  if (rul) rul.replaceChildren();
  const frows = byId("frows");
  if (frows) frows.replaceChildren();
  const agenda = byId("agenda-body");
  if (agenda) {
    const noev = el("div", "noev");
    noev.append(el("span", "t"), el("span", "n", "DATA UNAVAILABLE"));
    agenda.replaceChildren(noev);
  }
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
