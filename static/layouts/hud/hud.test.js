// Integration tests for the HUD layout's render hooks, run on Node's built-in
// runner with a MINIMAL hand-rolled DOM stub (the JS suite ships zero deps — no
// jsdom). Run:  node --test static/layouts/hud/hud.test.js
//
// Scope (the two things a pure geometry test can't reach):
//   1. every distinct weather-icons class the WMO table resolves to renders as a
//      `wi-<name>` class on a forecast row, with its condition text intact and
//      un-truncated (long strings included) — the "consume the resolved icon,
//      wrap without ellipsis" contract. `test_hud_glyphs.py` proves the other
//      half: all 28 WMO codes map onto exactly these classes, all in-font.
//   2. the six geometric marks (◆ ▸ ◂ ▲ ▼ ⟳) are drawn as SVG shapes, never
//      emitted as text that would fall back to a system font on the kiosk.
//
// Like app.test.js / geometry.test.js, `// @ts-check` is intentionally NOT on
// (no @types/node to resolve node:* builtins).

import test from "node:test";
import assert from "node:assert/strict";
import { localDayKey } from "../../core/time.js";

// ── minimal DOM stub ─────────────────────────────────────────────────────────

const XHTML_NS = "http://www.w3.org/1999/xhtml";

function makeClassList(node) {
  const parts = () => node._class.split(/\s+/).filter(Boolean);
  const has = (c) => parts().includes(c);
  return {
    add(...cs) {
      const set = new Set(parts());
      for (const c of cs) set.add(c);
      node._class = [...set].join(" ");
    },
    remove(...cs) {
      const set = new Set(parts());
      for (const c of cs) set.delete(c);
      node._class = [...set].join(" ");
    },
    toggle(c, on) {
      const want = on === undefined ? !has(c) : on;
      if (want) this.add(c);
      else this.remove(c);
    },
    contains: has,
  };
}

class El {
  constructor(doc, tag, ns) {
    this.doc = doc;
    this.tagName = tag;
    this.namespaceURI = ns || XHTML_NS;
    this._children = [];
    this._class = "";
    this._id = "";
    this._attrs = {};
    this.parent = null;
    this.hidden = false;
    this.clientHeight = 0; // 0 → renderAgenda skips its fit pass
    this.style = { setProperty(k, v) { this[k] = v; } };
    this.classList = makeClassList(this);
  }
  get className() { return this._class; }
  set className(v) { this._class = v == null ? "" : String(v); }
  get id() { return this._id; }
  set id(v) { this._id = String(v); this.doc._byId[this._id] = this; }
  setAttribute(k, v) {
    this._attrs[k] = String(v);
    if (k === "class") this._class = String(v);
    if (k === "id") this.id = String(v);
  }
  getAttribute(k) { return this._attrs[k] ?? null; }
  get children() { return this._children.filter((c) => c instanceof El); }
  get firstElementChild() { return this.children[0] ?? null; }
  _adopt(n) { if (n instanceof El) n.parent = this; return n; }
  append(...args) { for (const a of args) this._children.push(this._adopt(a)); }
  appendChild(n) { this._children.push(this._adopt(n)); return n; }
  replaceChildren(...args) { this._children = args.map((a) => this._adopt(a)); }
  before(n) {
    if (!this.parent) return;
    const i = this.parent._children.indexOf(this);
    this.parent._children.splice(i, 0, this.parent._adopt(n));
  }
  remove() {
    if (!this.parent) return;
    const i = this.parent._children.indexOf(this);
    if (i >= 0) this.parent._children.splice(i, 1);
  }
  get textContent() {
    return this._children.map((c) => (c instanceof El ? c.textContent : String(c))).join("");
  }
  set textContent(v) { this._children = v == null ? [] : [String(v)]; }
  // Height comes from the doc's installed measurer (see installHeights) so the
  // fit pass is exercisable; with none installed it is 0 (fit pass stays skipped).
  getBoundingClientRect() {
    const height = this.doc._measure ? this.doc._measure(this) : 0;
    return { height, width: 0, top: 0, left: 0, right: 0, bottom: 0 };
  }
  addEventListener(type, fn) {
    (this._listeners ??= {})[type] ??= [];
    this._listeners[type].push(fn);
  }
}

function makeDocument() {
  const doc = {
    _byId: {},
    createElement(tag) { return new El(this, tag); },
    createElementNS(ns, tag) { return new El(this, tag, ns); },
    getElementById(id) { return this._byId[id] ?? null; },
  };
  return doc;
}

// Depth-first collect every element carrying `cls`.
function allByClass(node, cls, out = []) {
  for (const c of node.children) {
    if (c.classList.contains(cls)) out.push(c);
    allByClass(c, cls, out);
  }
  return out;
}
const firstByClass = (node, cls) => allByClass(node, cls)[0] ?? null;

// Install a composable height model on the current document: a node whose class
// is in `heights` returns that fixed px (a leaf row); any other node sums its
// children — mirroring the no-gap flex-column invariant the pure planners assume,
// so the fit shell runs against deterministic, exact heights.
function installHeights(heights) {
  document._measure = function measure(node) {
    for (const cls of Object.keys(heights)) if (node.classList.contains(cls)) return heights[cls];
    return node.children.reduce((sum, c) => sum + measure(c), 0);
  };
}

// Synthesize a DOM event by invoking the handlers the stub recorded (tap→click).
function fire(node, type) {
  for (const fn of node._listeners?.[type] ?? []) fn();
}

// Local wall-clock ISO for today at hh:mm — localParts/localInstant read the
// wall-clock digits (the offset is ignored, see time.js), so this groups into
// today and compares against `now` in the machine's zone regardless of TZ.
function todayAt(hh, mm) {
  const today = localDayKey();
  return `${today}T${String(hh).padStart(2, "0")}:${String(mm).padStart(2, "0")}:00-00:00`;
}

// Date-only "YYYY-MM-DD" for today + n days, in the machine's local zone (so it
// groups the way the agenda splits days).
function dayKeyPlus(n) {
  const d = new Date();
  d.setDate(d.getDate() + n);
  return localDayKey(d);
}

globalThis.document = makeDocument();
const { layout, solarMarkerDecision, showEndOfSchedule } = await import("./index.js");

/** Fresh mount into a bare #app for each test (ids re-register on the doc). */
function freshMount() {
  globalThis.document = makeDocument();
  const root = document.createElement("div");
  root.id = "app";
  layout.mount(root);
  return root.children[0]; // the .screen.hud
}

// ── fixtures ─────────────────────────────────────────────────────────────────

// Every distinct weather-icons class app/weather_codes.py can resolve a WMO code
// to (the WiIcon Literal, minus wi-na which is the unknown fallback). If the
// renderer round-trips all of these, it round-trips any of the 28 codes, which
// map onto exactly this set (pinned by test_weather_codes.py + test_hud_glyphs.py).
const WI_ICONS = [
  "wi-day-sunny", "wi-night-clear", "wi-day-sunny-overcast", "wi-night-alt-cloudy-high",
  "wi-day-cloudy", "wi-night-alt-cloudy", "wi-cloudy", "wi-fog",
  "wi-day-sprinkle", "wi-night-alt-sprinkle", "wi-rain-mix", "wi-day-rain",
  "wi-night-alt-rain", "wi-day-snow", "wi-night-alt-snow", "wi-day-showers",
  "wi-night-alt-showers", "wi-day-sleet", "wi-sleet", "wi-thunderstorm",
];

/** @returns {import("../../core/contract.js").ForecastDay} */
function fday(icon, text, i) {
  return {
    date: `2026-07-${String((i % 27) + 1).padStart(2, "0")}`,
    code: 0,
    icon,
    text,
    high_f: 80 + (i % 5),
    low_f: 60 + (i % 5),
    precip_prob_pct: 40,
    precip_expected: i % 2 === 0,
  };
}

const CURRENT = {
  temp_f: 82, feels_like_f: 85, code: 2, text: "Partly cloudy", icon: "wi-day-cloudy",
  is_day: true, humidity_pct: 52, wind_mph: 7, precip_prob_pct: 15,
  high_f: 88, low_f: 71,
  sunrise: "2026-07-15T05:47:00-04:00", sunset: "2026-07-15T20:29:00-04:00",
};

const STATUS_DOC = {
  generated_at: "x", clock_synced: true,
  weather: { ok: true, fetched_at: "2026-07-15T09:40:00-04:00" },
  calendar: { ok: true, fetched_at: "2026-07-15T09:40:00-04:00" },
};

// Four in-window forecast days (highs 80–83, lows 60–63 via fday).
const fourDays = () => [0, 1, 2, 3].map((i) => fday("wi-day-sunny", "Clear", i));

// ── weather glyphs: every resolved icon renders, condition text intact ────────

test("renderForecast: each resolved icon class lands on its row's .wi glyph", () => {
  freshMount();
  // The panel shows 4 rows; walk the full vocabulary in chunks so every class
  // is exercised through the real renderer.
  for (let i = 0; i < WI_ICONS.length; i += 4) {
    const chunk = WI_ICONS.slice(i, i + 4);
    const days = chunk.map((icon, j) => fday(icon, `cond ${icon}`, i + j));
    layout.renderForecast(days);
    const rows = allByClass(document.getElementById("frows"), "frow");
    assert.equal(rows.length, chunk.length);
    rows.forEach((row, j) => {
      const glyph = firstByClass(row, "gl");
      assert.ok(glyph, "row has a .gl weather glyph");
      assert.ok(glyph.classList.contains("wi"), "glyph carries the .wi base class");
      assert.ok(glyph.classList.contains(chunk[j]), `glyph carries ${chunk[j]}`);
      // condition text is present verbatim (routed via textContent, not markup)
      const cond = firstByClass(row, "cond");
      assert.equal(cond.textContent, `cond ${chunk[j]}`);
    });
  }
});

test("renderForecast: long condition text is kept whole (no ellipsis truncation)", () => {
  freshMount();
  // Worst-case wrapping strings — the renderer must place them verbatim; the
  // 2-line wrap (no ellipsis) is enforced by layout.css (asserted in Python).
  const longs = ["Heavy freezing drizzle", "Thunderstorm with hail"];
  const days = longs.map((t, i) => fday("wi-rain-mix", t, i));
  layout.renderForecast(days);
  const conds = allByClass(document.getElementById("frows"), "cond");
  longs.forEach((t, i) => assert.equal(conds[i].textContent, t));
});

test("renderForecast: precip line shows only on precip_expected days", () => {
  freshMount();
  layout.renderForecast([
    fday("wi-day-rain", "Rain", 0), // even i → precip_expected true
    fday("wi-day-sunny", "Clear", 1), // odd i → false
  ]);
  const rows = allByClass(document.getElementById("frows"), "frow");
  assert.ok(firstByClass(rows[0], "pp").classList.contains("on"));
  assert.ok(!firstByClass(rows[1], "pp").classList.contains("on"));
});

// ── the six geometric marks are SVG, never text ──────────────────────────────

test("no geometric mark (◆ ▸ ◂ ▲ ▼ ⟳) is ever emitted as a text node", () => {
  const screen = freshMount();
  const today = localDayKey();
  layout.renderClock(new Date(), true);
  layout.renderCurrent({ ok: true, fetched_at: "x", current: CURRENT, forecast: [fday("wi-day-rain", "Rain", 0)] });
  layout.renderForecast([fday("wi-day-rain", "Rain", 0)]);
  layout.renderAgenda(
    [
      { start: today, all_day: true, title: "Independence Day", kind: "observance" },
      { start: `${today}T00:00:00-04:00`, end: `${today}T23:59:00-04:00`, all_day: false, title: "Focus block", kind: "personal" },
    ],
    true,
    true,
  );
  layout.renderStatus(
    { generated_at: "x", clock_synced: true, weather: { ok: true, fetched_at: "2026-07-15T09:40:00-04:00" }, calendar: { ok: true, fetched_at: "2026-07-15T09:40:00-04:00" } },
    { refresh: async () => {} },
  );

  const text = screen.textContent;
  for (const mark of ["◆", "▸", "◂", "▲", "▼", "⟳"]) {
    assert.ok(!text.includes(mark), `rendered text must not contain the raw mark ${mark}`);
  }
});

test("the reachable marks are drawn as <svg> shapes with their sym class", () => {
  const screen = freshMount();
  const today = localDayKey();
  layout.renderCurrent({ ok: true, fetched_at: "x", current: CURRENT, forecast: [fday("wi-day-rain", "Rain", 0)] });
  layout.renderAgenda(
    [
      { start: today, all_day: true, title: "Independence Day", kind: "observance" }, // ◆ diamond
      { start: `${today}T00:00:00-04:00`, end: `${today}T23:59:00-04:00`, all_day: false, title: "Focus block", kind: "personal" }, // ◂ active tag
    ],
    true,
    true,
  );
  layout.renderStatus({ generated_at: "x", clock_synced: true, weather: { ok: true, fetched_at: "2026-07-15T09:40:00-04:00" }, calendar: { ok: true, fetched_at: "2026-07-15T09:40:00-04:00" } }, { refresh: async () => {} });

  for (const cls of ["sym-diamond", "sym-left", "sym-resync"]) {
    const node = firstByClass(screen, cls);
    assert.ok(node, `${cls} is present`);
    assert.equal(node.tagName, "svg", `${cls} is an <svg> element, not text`);
  }
  // ▲ / ▼ solar labels are SVG polygons inside the tape (class s-tri).
  const tris = allByClass(screen, "s-tri");
  assert.equal(tris.length, 2, "sunrise ▲ and sunset ▼ are SVG polygons");
  assert.equal(tris[0].tagName, "polygon");
});

// ── clock / current wiring smoke ─────────────────────────────────────────────

test("renderClock: zero-padded hour + uppercase date + sync warning toggle", () => {
  freshMount();
  layout.renderClock(new Date(2026, 6, 15, 14, 6), true);
  assert.equal(document.getElementById("clock").textContent, "02:06");
  assert.equal(document.getElementById("ampm").textContent, "PM");
  // Independent expectation (NOT the element's own text): pins the date CONTENT +
  // uppercasing via a fresh Date, robust to the runner's locale.
  const expectedDate = new Date(2026, 6, 15)
    .toLocaleDateString(undefined, { weekday: "long", month: "long", day: "numeric" })
    .toUpperCase();
  assert.equal(document.getElementById("hdate").textContent, expectedDate);
  assert.equal(document.getElementById("clock-warn").hidden, true);
  layout.renderClock(new Date(2026, 6, 15, 14, 6), false);
  assert.equal(document.getElementById("clock-warn").hidden, false);
});

test("renderCurrent: computes the shared scale label + fills the docks", () => {
  freshMount();
  layout.renderCurrent({ ok: true, fetched_at: "x", current: CURRENT, forecast: [fday("wi-day-rain", "Rain", 0), fday("wi-day-snow", "Snow", 1)] });
  // window over [82,88,71,60,80,61,81]: min 60 lands on a gridline → drops one
  // step to 50; span 40 → 50–90 (hi 88 fits).
  assert.equal(document.getElementById("scaleLbl").textContent, "SCALE 50–90");
  assert.equal(document.getElementById("d-feels").textContent, "85°");
  assert.equal(document.getElementById("d-wind").textContent, "7");
  assert.equal(document.getElementById("mode").textContent, "DAY");
});

// ── shared scale coupling (renderCurrent → renderForecast) ───────────────────

test("shared scale: renderForecast uses the window renderCurrent seeded (today incl.)", () => {
  freshMount();
  // current high 105 widens the shared window to 50–110; the forecast temps
  // alone would only reach 50–90, so a 110 ruler numeral proves renderForecast
  // read the shared window, not a forecast-only fallback.
  layout.renderCurrent({ ok: true, fetched_at: "x", current: { ...CURRENT, high_f: 105 }, forecast: fourDays() });
  layout.renderForecast(fourDays());
  const rul = document.getElementById("rul");
  assert.deepEqual(rul.children.map((s) => s.textContent), ["50", "70", "90", "110"]);
});

test("shared scale: mount() clears the window so a remount can't leak a stale one", () => {
  freshMount();
  layout.renderCurrent({ ok: true, fetched_at: "x", current: { ...CURRENT, high_f: 105 }, forecast: fourDays() }); // sets 50–110
  const root2 = document.createElement("div");
  root2.id = "app2";
  layout.mount(root2); // MUST reset scaleWindow → null
  layout.renderForecast(fourDays()); // falls back to forecast-only 50–90
  const rul = document.getElementById("rul");
  // 4 numerals (…110) here would mean the stale 50–110 leaked past the remount.
  assert.deepEqual(rul.children.map((s) => s.textContent), ["50", "70", "90"]);
});

test("renderCurrent: seeds the scale from only the first 4 days (>4-day feed can't stretch it)", () => {
  freshMount();
  const forecast = fourDays();
  forecast.push({ ...fday("wi-day-sunny", "Hot", 4), high_f: 130, low_f: 120 });
  forecast.push({ ...fday("wi-day-sunny", "Hot", 5), high_f: 135, low_f: 125 });
  layout.renderCurrent({ ok: true, fetched_at: "x", current: CURRENT, forecast });
  // Seeded from days 0–3 + today only → 50–90; days 4–5 (130/135) are excluded.
  assert.equal(document.getElementById("scaleLbl").textContent, "SCALE 50–90");
});

// ── solar marker decision (pure) ─────────────────────────────────────────────

test("solarMarkerDecision: shows in-day, hides + clamps off-tape", () => {
  const mk = (fraction) => ({ fraction, nowX: 52 + (488 - 52) * fraction, sunriseX: 52, sunsetX: 488 });
  assert.deepEqual(solarMarkerDecision(mk(0)), { show: true, travelX: 52 }); // sunrise
  assert.deepEqual(solarMarkerDecision(mk(1)), { show: true, travelX: 488 }); // sunset
  const before = solarMarkerDecision(mk(-0.2)); // pre-dawn
  assert.equal(before.show, false);
  assert.equal(before.travelX, 52); // clamped back onto the tape start
  const after = solarMarkerDecision(mk(1.5)); // post-dusk
  assert.equal(after.show, false);
  assert.equal(after.travelX, 488); // clamped onto the tape end
});

// ── END OF SCHEDULE gate (pure) ──────────────────────────────────────────────

test("showEndOfSchedule: only when whole schedule shown and the closure fits", () => {
  assert.equal(showEndOfSchedule(false, false, 30, 200), true);
  assert.equal(showEndOfSchedule(true, false, 30, 200), false); // something truncated
  assert.equal(showEndOfSchedule(false, true, 30, 200), false); // a "+N …" line present
  assert.equal(showEndOfSchedule(false, false, 250, 200), false); // closure overflows
});

// ── agenda fit shell (real DOM path, deterministic heights) ──────────────────

test("fit: overflow drops later days first (today protected) + '+N more days'", () => {
  freshMount();
  installHeights({ dhead: 10, ev: 10, more: 10, noev: 10, eom: 10 });
  // today + 3 future all-day rows → 4 sections × 20px = 80px; budget 50px.
  const events = [0, 1, 2, 3].map((n) => ({ start: dayKeyPlus(n), all_day: true, title: `E${n}`, kind: "personal" }));
  document.getElementById("agenda-body").clientHeight = 50;
  layout.renderAgenda(events, true, true);
  const col = document.getElementById("agenda-body").children[0];
  assert.equal(allByClass(col, "dsection").length, 2, "today + 1 day kept, 2 later days dropped");
  const more = firstByClass(col, "more");
  assert.equal(more.textContent, "+2 more days");
  assert.equal(allByClass(col, "eom").length, 0, "no END OF SCHEDULE when truncated");
});

test("fit: today's past events roll into a '+N earlier' line when today overflows", () => {
  freshMount();
  installHeights({ dhead: 10, ev: 10, more: 10 });
  // today only: 3 past timed rows + 1 future (the next-up); section 50px, budget 40.
  const events = [
    { start: todayAt(0, 1), end: todayAt(0, 2), all_day: false, title: "P1", kind: "personal" },
    { start: todayAt(0, 3), end: todayAt(0, 4), all_day: false, title: "P2", kind: "personal" },
    { start: todayAt(0, 5), end: todayAt(0, 6), all_day: false, title: "P3", kind: "personal" },
    { start: todayAt(23, 58), end: todayAt(23, 59), all_day: false, title: "PFUT", kind: "personal" },
  ];
  document.getElementById("agenda-body").clientHeight = 40;
  layout.renderAgenda(events, true, true);
  const col = document.getElementById("agenda-body").children[0];
  const more = firstByClass(col, "more");
  assert.equal(more.textContent, "+2 earlier");
  assert.equal(allByClass(col, "ev").length, 2, "2 oldest past rows rolled off");
});

test("fit: END OF SCHEDULE closes an untruncated schedule (budget fits)", () => {
  freshMount();
  installHeights({ dhead: 10, ev: 10, more: 10, noev: 10, eom: 10 });
  document.getElementById("agenda-body").clientHeight = 200;
  layout.renderAgenda([], true, true); // empty today → NO ENTRIES, everything fits
  const col = document.getElementById("agenda-body").children[0];
  const noev = firstByClass(col, "noev");
  assert.equal(noev.textContent, "— NO ENTRIES —");
  const eom = firstByClass(col, "eom");
  assert.ok(eom, "END OF SCHEDULE closure present");
  assert.equal(eom.textContent, "END OF SCHEDULE");
});

// ── empty-agenda states + cold-boot degrade ──────────────────────────────────

test("renderAgenda: an empty day (holiday only, no rows) shows '— NO ENTRIES —'", () => {
  freshMount();
  const events = [
    { start: todayAt(9, 0), all_day: false, title: "Standup", kind: "personal" },
    { start: dayKeyPlus(1), all_day: true, title: "Holiday X", kind: "holiday" },
  ];
  layout.renderAgenda(events, true, true); // clientHeight 0 → no fit pass, states still build
  const col = document.getElementById("agenda-body").children[0];
  const sections = allByClass(col, "dsection");
  assert.equal(sections.length, 2);
  // The future day carries the holiday as a header pill and NO ENTRIES for rows.
  const future = sections[1];
  assert.ok(firstByClass(future, "hol"), "holiday rendered as a header pill");
  assert.equal(firstByClass(future, "noev").textContent, "— NO ENTRIES —");
});

test("renderUnavailable: every region gets an honest placeholder (no half-blank panel)", () => {
  freshMount();
  layout.renderUnavailable();
  assert.equal(document.getElementById("gsvg").textContent, "WEATHER UNAVAILABLE");
  for (const id of ["d-feels", "d-hum", "d-rain", "d-wind"]) {
    assert.equal(document.getElementById(id).textContent, "—");
  }
  assert.equal(document.getElementById("ssvg").children.length, 0, "solar tape cleared");
  assert.equal(document.getElementById("rul").children.length, 0, "ruler cleared");
  assert.equal(document.getElementById("frows").children.length, 0, "forecast rows cleared");
  assert.equal(document.getElementById("agenda-body").textContent, "DATA UNAVAILABLE");
});

// ── status: stale + manual refresh UX ────────────────────────────────────────

test("renderStatus: opts.stale flips both chips STALE and blanks the stamp", () => {
  freshMount();
  layout.renderStatus(STATUS_DOC, { stale: true });
  const status = document.getElementById("status");
  const chips = allByClass(status, "ok");
  assert.equal(chips.length, 2);
  assert.deepEqual(chips.map((c) => c.textContent), ["WEATHER STALE", "CALENDAR STALE"]);
  assert.ok(chips.every((c) => c.classList.contains("stale")));
  assert.equal(firstByClass(status, "upd").textContent, "UPDATED —");
});

test("renderStatus: RESYNC wires opts.refresh — spins, guards double-tap, then stops", async () => {
  freshMount();
  let calls = 0;
  let release;
  const gate = new Promise((r) => { release = r; });
  layout.renderStatus(STATUS_DOC, { refresh: async () => { calls++; await gate; } });
  const resync = document.getElementById("resync");
  assert.ok(resync, "RESYNC chip present");
  fire(resync, "click");
  assert.ok(resync.classList.contains("is-spinning"), "spins while in flight");
  fire(resync, "click"); // double-tap while refreshing → ignored
  release();
  await new Promise((r) => setImmediate(r));
  assert.equal(calls, 1, "double-tap guarded — refresh ran once");
  assert.ok(!document.getElementById("resync").classList.contains("is-spinning"), "spin cleared");
});

test("renderStatus: a failed refresh flashes the RESYNC error, then clears", async (t) => {
  t.mock.timers.enable({ apis: ["setTimeout"] });
  t.mock.method(console, "error", () => {}); // the SUT logs the failure — expected
  freshMount();
  layout.renderStatus(STATUS_DOC, { refresh: async () => { throw new Error("boom"); } });
  const resync = document.getElementById("resync");
  fire(resync, "click");
  await new Promise((r) => setImmediate(r)); // let the rejection propagate + flash
  assert.ok(resync.classList.contains("is-error"), "error flashed");
  t.mock.timers.tick(1500);
  assert.ok(!document.getElementById("resync").classList.contains("is-error"), "error cleared");
});
