// HUD layout — the instrument-HUD design (design-mocks/instrument-hud-d.html),
// ported as the second selectable layout. Exports a `layout` object implementing
// the seven-hook Layout interface (see core/contract.js): mount() builds the
// phosphor-CRT shell into the bare <div id="app">, and the per-region renderers
// fill it from the data contract.
//
// The three instruments (240° temp dial + solar day-tape = SVG; forecast range
// plot = positioned HTML markers) consume the PURE geometry modules under
// ./geometry/ — this file writes only the imperative createElementNS/DOM walk
// that turns their specs into nodes; it never re-derives the math.
//
// Port constraints (from the plan):
//  - hot-tier SVG colors live in CLASSES (styled in layout.css), never inline
//    style="", so the CSS palette cascade can retint the HUD via a hue theme;
//  - the six geometric marks ◆ ▸ ◂ ▲ ▼ ⟳ are NOT in the vendored mono fonts, so
//    they are drawn as inline SVG shapes here, never emitted as text that would
//    fall back to a system font on the kiosk;
//  - weather glyphs reuse the vendored weather-icons font (the server-resolved
//    `icon` class), phosphor-styled — not hand-drawn SVG.
//
// Importing this module runs no side effects — the DOM is touched only inside
// mount()/the render hooks, driven by the core state machine's init().

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

const SVG_NS = "http://www.w3.org/2000/svg";

// ── small builders ─────────────────────────────────────────────────────────

/** @param {string} id @returns {HTMLElement | null} */
const byId = (id) => document.getElementById(id);

// Namespaced SVG element with attribute + optional text convenience. Colors are
// never set here — SVG elements carry CLASSES and layout.css styles them, so the
// palette cascade wins (the hard port constraint). Attributes are geometry only.
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

// ── the six geometric marks, as inline SVG (NOT font glyphs) ─────────────────
// ◆ ▸ ◂ ▲ ▼ ⟳ are absent from the vendored mono subset (subset-manifest.txt), so
// drawing them as shapes is what keeps them off system-font fallback on the Pi.
// Each is UI furniture; fill/stroke come from layout.css via the class.

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

// ⟳ RESYNC / refresh — the classic layout's two-path arc, drawn as SVG so it
// never relies on the U+27F3 font glyph the subset lacks.
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

// Build the full HUD DOM shell into the bare mount root: the phosphor canvas
// (.screen — base owns its sizing/clipping), a chronometer header, the weather
// stack (dial · solar tape · forecast) + agenda in the main grid, and the status
// footer. The renderers below fill the id'd regions; the instrument frames,
// labels, ruler strips and CRT overlay are static furniture built once here.
/** @param {HTMLElement} root @returns {void} */
function mount(root) {
  // Clear the shared scale (declared below) so a remount can never read a window
  // left over from a previous mount / render cycle.
  scaleWindow = null;

  const screen = el("div", "screen hud");

  // corner-bracket frame for an instrument panel (the mock's .brk + .c2).
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
  // Clock-sync warning — shown only when the Pi clock is NOT NTP-synced.
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
  footer.append(el("span", "fticks"));

  screen.append(header, main, footer);
  // cheap CRT dressing: scanlines + vignette (one static overlay)
  screen.append(el("div", "fx"));
  root.append(screen);
}

// ── clock ──────────────────────────────────────────────────────────────────

// Live wall-clock from the browser (the one time source NOT taken from the API),
// plus the clock-sync warning. Hour is zero-padded to match the HUD chronometer.
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

// The shared temperature window both the dial (renderCurrent) and the forecast
// range plot + ruler (renderForecast) render against. Computed once per poll in
// renderCurrent — which receives the WHOLE weather block, forecast included — so
// the two instruments always share ONE scale. renderForecast reads it back.
// INVARIANT: core/machine.js always calls renderCurrent BEFORE renderForecast on
// a paint, so the window is fresh when the forecast reads it; mount() resets it
// to null so a remount can't leak a stale window across renders/tests.
/** @type {ScaleWindow | null} */
let scaleWindow = null;

/** @param {string} id @param {number} value @param {string} [unit] @returns {void} */
function setDock(id, value, unit) {
  const n = byId(id);
  if (!n) return;
  n.replaceChildren(String(value));
  if (unit) n.append(el("small", null, unit));
}

// Minutes-of-day (0–1439) from an ISO string's local wall-clock part, or null
// for a date-only / malformed stamp (contract drift → the tape hides its bugs).
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
  // Seed the scale from the SAME first-4 days renderForecast plots, so a backend
  // that ever returns >4 days can't stretch the window off the visible rows.
  const forecast = (weather.forecast ?? []).slice(0, 4);

  // one shared scale over every temperature on screen (mock's allTemps set).
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

// The 240° temp dial: baseline arc, value arc (fat glow understroke + bright
// stroke), ticks/numerals, and the center readout stack (big temp · condition ·
// H/L). All paths/points come from dialGeometry; every color is a class.
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
  // center readout — baselines are dial-specific layout constants (mock lines
  // 442-456), not geometry: temp on CY, condition + H/L below.
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
 * Marker SHOW/HIDE + traveled-line endpoint for the solar tape. The geometry's
 * `fraction`/`nowX` are RAW (see solar.js): at night `fraction` is outside [0,1]
 * and `nowX` falls off the tape. Show the now-marker only in-day; the traveled
 * line consumes the spec's already-computed `nowX` and is only CLAMPED to the
 * daylight span for the off-tape (night) case — no re-derivation of the mapping.
 * @param {Pick<SolarGeometry, "fraction" | "nowX" | "sunriseX" | "sunsetX">} s
 * @returns {{ show: boolean, travelX: number }}
 */
export function solarMarkerDecision(s) {
  const show = s.fraction >= 0 && s.fraction <= 1;
  const travelX = Math.min(s.sunsetX, Math.max(s.sunriseX, s.nowX));
  return { show, travelX };
}

// The solar day-progress tape. Night mode is out of scope, so the renderer hides
// the now-marker + NOW label off-tape and clamps the traveled line to the
// daylight span via solarMarkerDecision (a renderer call — the geometry stays raw).
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

  // dashed baseline + idle ticks
  ssvg.append(svg("line", { class: "s-baseline", x1: s.baseline.x1, y1: s.baseline.y1, x2: s.baseline.x2, y2: s.baseline.y2 }));
  for (const t of s.idleTicks) ssvg.append(svg("line", { class: "s-idle", x1: t.x1, y1: t.y1, x2: t.x2, y2: t.y2 }));

  // traveled daylight portion (glow understroke + bright stroke), clamped
  ssvg.append(svg("line", { class: "s-travel-glow", x1: s.sunriseX, y1: s.ty, x2: travelX, y2: s.ty }));
  ssvg.append(svg("line", { class: "s-travel", x1: s.sunriseX, y1: s.ty, x2: travelX, y2: s.ty }));

  // sunrise / sunset bugs
  for (const b of s.bugs) ssvg.append(svg("line", { class: "s-bug", x1: b.x1, y1: b.y1, x2: b.x2, y2: b.y2 }));

  // sun marker + NOW label — only while the sun is actually on the tape
  if (inDay) {
    const m = s.sunMarker;
    ssvg.append(svg("circle", { class: "s-halo", cx: m.cx, cy: m.cy, r: m.haloR }));
    ssvg.append(svg("circle", { class: "s-ring", cx: m.cx, cy: m.cy, r: m.ringR }));
    for (const t of m.crossTicks) ssvg.append(svg("line", { class: "s-cross", x1: t.x1, y1: t.y1, x2: t.x2, y2: t.y2 }));
    ssvg.append(svg("text", { class: "s-now", x: m.cx + 16, y: s.ty - 9 }, "NOW"));
  }

  // labels: ▲ SUNRISE · SUNSET ▼ · DAYLIGHT (▲▼ drawn as polygons, not glyphs)
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

// A weather <i class="wi wi-…"> glyph (server-resolved icon class → the vendored
// font, phosphor-styled). The icon class is an OWN value; human condition text
// is always routed through textContent.
/** @param {string} iconClass @param {string} [extra] @returns {HTMLElement} */
function wiIcon(iconClass, extra) {
  return el("i", "wi " + iconClass + (extra ? " " + extra : ""));
}

// The amber precip teardrop (mock's inline SVG), drawn as a shape so its stroke
// follows the palette via a class rather than a hardcoded color.
/** @returns {SVGElement} */
function precipDrop() {
  const s = svg("svg", { class: "pp-drop", viewBox: "0 0 10 14", "aria-hidden": "true" });
  s.append(svg("path", { d: "M5 1 C5 1 1.6 6.4 1.6 9.2 a3.4 3.4 0 0 0 6.8 0 C8.4 6.4 5 1 5 1 Z" }));
  return s;
}

/** @param {ForecastDay[]} forecast @returns {void} */
function renderForecast(forecast) {
  const days = forecast.slice(0, 4);
  // Prefer the scale computed in renderCurrent (covers today's temps too); fall
  // back to the forecast temps alone if renderForecast somehow runs first.
  const plotWindow =
    scaleWindow ?? computeScaleWindow(days.flatMap((f) => [f.low_f, f.high_f]));

  // ruler: numerals every 20° + the minor-tick gradient (division count as a CSS
  // custom prop so the gradient rule — and its themeable colors — stay in CSS).
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
      wiIcon(f.icon, "gl"),
      el("span", "cond", f.text), // human text — wraps to 2 lines, no ellipsis
      el("span", "lo", `${f.low_f}°`),
      track,
      el("span", "hi", `${f.high_f}°`),
      pp,
    );
    root.append(row);
  });
}

// ── agenda manifest (single column, day headers) ─────────────────────────────

// First descendant carrying `cls`, DOM-walk (works with real + stub nodes).
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
  p.append(symDiamond(), el("span", "hol-t", title)); // title as text — never HTML
  return p;
}

// One personal/info event row. Holiday/observance pills are pulled into the day
// header instead (see daySection). `isActive` marks the next-up event ("◂ ACTIVE"),
// `isPast` tags an already-past row for the roll-off pass — both apply only to a
// timed personal row.
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
  row.append(t, el("span", "n", ev.title)); // title as text — never HTML
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

  // holiday/observance items become header pills; personal/info become rows.
  const pills = group.items.filter((i) => i.kind === "holiday" || i.kind === "observance");
  const rows = group.items.filter((i) => i.kind === "personal" || i.kind === "info");
  for (const p of pills) dhead.append(holPill(p.title));

  const events = el("div", "day-events");
  // "Today awareness": next-up + roll-off share one gate (today, trustworthy
  // clock) and one `now`; picked by object identity so partitioning above can't
  // misalign the indices nextUp/pastIndexes return over the full item list.
  const aware = isToday && clockSynced !== false;
  const now = new Date();
  const nextIdx = aware ? nextUp(group.items, now) : -1;
  const nextEv = nextIdx >= 0 ? group.items[nextIdx] : null;
  const pastSet = new Set(aware ? pastIndexes(group.items, now).map((i) => group.items[i]) : []);
  for (const ev of rows) events.append(eventNode(ev, ev === nextEv, pastSet.has(ev)));

  // Empty day (no personal/info rows) → a "— NO ENTRIES —" line, matching the
  // -empty mock. Suppressed on a stale/failed calendar: we can't claim emptiness.
  if (rows.length === 0 && calendarOk) {
    const noev = el("div", "noev");
    noev.append(el("span", "t"), el("span", "n", "— NO ENTRIES —"));
    events.append(noev);
  }
  section.append(dhead, events);
  return section;
}

// Height a "+N …" summary line will occupy, measured with a real (briefly
// attached) placeholder — an estimate could under-reserve. Any one-line label
// measures the same, so a "+0 more" probe stands in.
/** @param {Element} container @returns {number} */
function measureLine(container) {
  const probe = moreLine("+0 more");
  container.append(probe);
  const h = rowH(probe);
  probe.remove();
  return h;
}

// Trim a day-section's event rows in place until the whole section fits `budget`
// px — the imperative shell around the pure planDayFit (its roll-off/trim
// contract). The day header (+ its pills) sit outside .day-events, so they are
// never trimmed. Returns whether anything was hidden.
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

// Fit the single agenda column into `budget` px without clipping. Reuses the
// core planners: planColumnFit drops whole later days from the end (today is
// index 0, protected) + a "+N more days" footer; if today alone still overflows
// its fair share of the budget, its events are trimmed via planDayFit. Returns
// whether the schedule was truncated at all (drives the END OF SCHEDULE closure).
/** @param {Element} col @param {number} budget @returns {boolean} */
function fitColumnInPlace(col, budget) {
  const sections = [...col.children];
  if (sections.length === 0) return false;
  const footerH = measureLine(col);
  const plan = planColumnFit(rowH(col), sections.map(rowH), footerH, budget);
  for (let k = 0; k < plan.dropCount; k++) sections[sections.length - 1 - k].remove();

  // Today-trim only fires when planColumnFit has dropped EVERY later day (its
  // loop stops at index 1), so `kept` is [today] alone here and `showFooter` is
  // false — the otherH sum is 0 and the footer term drops out. The general form
  // is kept (totality) so the arithmetic stays correct if the planner contract
  // ever changes.
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

// Whether the END OF SCHEDULE closure should show: only when the whole schedule
// is displayed — nothing dropped or trimmed (`truncated` false) and no "+N …"
// summary line present — AND the closure itself still fits the budget.
/** @param {boolean} truncated @param {boolean} hasMore @param {number} colHeight @param {number} budget @returns {boolean} */
export function showEndOfSchedule(truncated, hasMore, colHeight, budget) {
  return !truncated && !hasMore && colHeight <= budget;
}

/** @param {AgendaItem[]} events @param {boolean} [calendarOk] @param {boolean} [clockSynced] @returns {void} */
function renderAgenda(events, calendarOk = true, clockSynced = true) {
  // Guarantee today leads so the manifest opens on today (with its "— NO
  // ENTRIES —" line when today is quiet).
  const groups = withTodayGroup(groupByDay(events), localDayKey());
  const root = byId("agenda-body");
  if (!root) return;
  // The measured column lives INSIDE the clipping/budget container: root's
  // height is flex-clamped to the panel, so measuring it always equals the
  // budget. `col` (flex:0 0 auto) keeps its natural content height — the true
  // fit input — and overflows into root's overflow:hidden (mirrors classic's
  // agenda-body → agenda-col split).
  const col = el("div", "acol");
  root.replaceChildren(col);
  for (const group of groups) col.append(daySection(group, calendarOk, clockSynced));

  // Measure-and-fit pass (after layout, so heights are real). budget<=0 (e.g.
  // an unlaid-out/headless render) → skip fit and the closure entirely.
  const budget = root.clientHeight;
  if (budget > 0) {
    const truncated = fitColumnInPlace(col, budget);
    // END OF SCHEDULE closure (mock -empty ref): append, then keep only if the
    // pure gate agrees — measured WITH the closure so its own height counts.
    const hasMore = Boolean(findByClass(col, "more"));
    const eom = el("div", "eom");
    eom.append(el("span", "erule"), el("span", "eom-t", "END OF SCHEDULE"), el("span", "erule"));
    col.append(eom);
    if (!showEndOfSchedule(truncated, hasMore, rowH(col), budget)) eom.remove();
  }
}

// ── status + manual refresh ──────────────────────────────────────────────────

// True while a manual POST /refresh is in flight; guards a double-tap and is the
// source of truth for the spin across renderStatus rebuilds.
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

// One "● LABEL OK/STALE" annunciator chip.
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
  status.replaceChildren(el("span", "fticks"));
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

// Cold-boot degrade: honest placeholders so no region is a blank instrument.
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
