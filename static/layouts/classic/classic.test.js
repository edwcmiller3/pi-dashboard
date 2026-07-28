// Behavioral tests for the classic layout's DOM renderers, fit shells, and
// degrade paths. Run with Node's built-in runner (no deps):  node --test  (from static/)
//
// The classic layout is the only piece of the module graph that touches the DOM,
// so app.test.js (the pure-core suite) can't cover it. This file drives the layout
// against a tiny, dependency-free DOM stub defined locally below - just enough of
// the surface classic/index.js uses (createElement/getElementById, append/
// replaceChildren/remove/before, classList, textContent, getBoundingClientRect,
// clientHeight). It is deliberately NOT a shared module: it exists to prove a
// classic behavior regression fails `node --test`, not only the out-of-band pixel
// mockup. The pure fit PLANNERS (planDayFit/planColumnFit) are unit-tested
// in ../../app.test.js; here we prove the imperative SHELL wires real measurements
// into the plan and applies it to the DOM (inserts "+N earlier"/"+N more"/"+N more
// days", removes children).
//
// Typing mirrors app.test.js: JSDoc typedefs document the fixtures, but `// @ts-check`
// is intentionally off (the package ships no @types/node, so `node:*` builtins
// wouldn't resolve). Clock-dependent tests freeze time via `t.mock.timers` so the
// "today awareness" logic (next-up / roll-off) can't flake across local midnight.

import test, { mock } from "node:test";
import assert from "node:assert/strict";

// ── minimal DOM stub (local, dep-free) ────────────────────────────────────────

// Leaf render height (px) every element with no ELEMENT children reports; a
// container's height is the sum of its element children's heights, so removals
// compose linearly - the invariant the fit planners assume (see core/agenda.js).
const LEAF_H = 10;

/** A stub Element: only the surface classic/index.js exercises. */
class El {
  /** @param {string} tag */
  constructor(tag) {
    this.tagName = tag;
    /** @type {(El | { textContent: string })[]} */
    this.childNodes = [];
    /** @type {El | null} */
    this.parent = null;
    this._classes = new Set();
    this._attrs = {};
    this._id = "";
    this._html = "";
    this.hidden = false;
    this._clientHeight = 0;
    const self = this;
    this.classList = {
      /** @param {...string} cs */
      add: (...cs) => cs.forEach((c) => self._classes.add(c)),
      /** @param {...string} cs */
      remove: (...cs) => cs.forEach((c) => self._classes.delete(c)),
      /** @param {string} c @param {boolean} [on] */
      toggle: (c, on) => {
        const v = on === undefined ? !self._classes.has(c) : on;
        if (v) self._classes.add(c);
        else self._classes.delete(c);
        return v;
      },
      /** @param {string} c */
      contains: (c) => self._classes.has(c),
    };
  }

  get className() {
    return [...this._classes].join(" ");
  }
  set className(v) {
    this._classes = new Set(String(v).split(/\s+/).filter(Boolean));
  }

  get id() {
    return this._id;
  }
  set id(v) {
    this._id = v;
    doc._byId.set(v, this);
  }

  get textContent() {
    return this.childNodes.map((n) => String(n.textContent)).join("");
  }
  set textContent(v) {
    this.childNodes = [{ textContent: String(v) }];
  }

  set innerHTML(v) {
    this._html = v;
  }

  /** Element children only (text nodes excluded), like the real .children. */
  get children() {
    return this.childNodes.filter((n) => n instanceof El);
  }
  get firstElementChild() {
    return this.children[0] ?? null;
  }

  /** @param {...(El | string)} nodes */
  append(...nodes) {
    for (const n of nodes) {
      if (typeof n === "string") this.childNodes.push({ textContent: n });
      else {
        n.parent = this;
        this.childNodes.push(n);
      }
    }
  }
  /** @param {...(El | string)} nodes */
  replaceChildren(...nodes) {
    this.childNodes = [];
    this.append(...nodes);
  }
  remove() {
    const p = this.parent;
    if (p) {
      const i = p.childNodes.indexOf(this);
      if (i >= 0) p.childNodes.splice(i, 1);
    }
    this.parent = null;
  }
  /** @param {El} node */
  before(node) {
    const p = this.parent;
    if (!p) return;
    const i = p.childNodes.indexOf(this);
    p.childNodes.splice(i, 0, node);
    node.parent = p;
  }

  /** @param {string} k @param {string} v */
  setAttribute(k, v) {
    this._attrs[k] = v;
  }
  addEventListener() {}

  /** @param {string} sel @returns {El | null} */
  querySelector(sel) {
    return find(this, matcher(sel));
  }

  getBoundingClientRect() {
    return { height: measure(this) };
  }
  get clientHeight() {
    return this._clientHeight;
  }
}

/** @param {El} node @returns {number} */
function measure(node) {
  const kids = node.children;
  if (kids.length === 0) return LEAF_H;
  return kids.reduce((sum, c) => sum + measure(c), 0);
}

/** @param {string} sel @returns {(el: El) => boolean} */
function matcher(sel) {
  if (sel[0] === ".") return (el) => el._classes.has(sel.slice(1));
  if (sel[0] === "#") return (el) => el._id === sel.slice(1);
  return (el) => el.tagName === sel;
}

/** @param {El} root @param {(el: El) => boolean} match @returns {El | null} */
function find(root, match) {
  for (const c of root.children) {
    if (match(c)) return c;
    const r = find(c, match);
    if (r) return r;
  }
  return null;
}

const doc = {
  /** @type {Map<string, El>} */
  _byId: new Map(),
  /** @type {El | null} */
  _appRoot: null,
  /** @param {string} tag */
  createElement: (tag) => new El(tag),
  /** @param {string} id */
  getElementById: (id) => doc._byId.get(id) ?? null,
  /** @param {string} sel */
  querySelector: (sel) => (doc._appRoot ? find(doc._appRoot, matcher(sel)) : null),
};

// classic/index.js + core/dom.js reach the DOM through the global `document`;
// wire the stub in before any test runs (module top level runs before tests).
globalThis.document = /** @type {any} */ (doc);

// The layout under test - imported AFTER the global is set (its functions only
// touch document at call time, but keep the ordering obvious).
const { layout } = await import("./index.js");

// ── test helpers ──────────────────────────────────────────────────────────────

/** Fresh shell per test: build #app, mount the layout into it. @returns {El} */
function mountShell() {
  const app = new El("div");
  app.id = "app";
  doc._appRoot = app;
  layout.mount(app);
  return app;
}

/** Collect every element under `root` carrying `cls`. @param {El} root @param {string} cls @returns {El[]} */
function withClass(root, cls) {
  const out = [];
  for (const c of root.children) {
    if (c._classes.has(cls)) out.push(c);
    out.push(...withClass(c, cls));
  }
  return out;
}

/** Freeze the clock at local noon on 2026-07-01 (mid-afternoon events sort cleanly). @param {any} t */
function freezeNoon(t) {
  const noon = new Date(2026, 6, 1, 12, 0, 0).getTime();
  t.mock.timers.enable({ apis: ["Date"] });
  t.mock.timers.setTime(noon);
}

const TODAY = "2026-07-01";
/** A timed personal event on TODAY; offset is cosmetic (localParts reads literals). */
const timed = (title, hh, endHh) => ({
  start: `${TODAY}T${String(hh).padStart(2, "0")}:00:00-04:00`,
  end: `${TODAY}T${String(endHh).padStart(2, "0")}:00:00-04:00`,
  all_day: false,
  title,
  kind: "personal",
});

/** @returns {any} A contract-shaped current-weather block. */
const weatherFixture = () => ({
  ok: true,
  fetched_at: "2026-07-01T09:40:00-04:00",
  current: {
    temp_f: 72,
    feels_like_f: 70,
    code: 1,
    text: "Mostly Sunny",
    icon: "wi-day-sunny",
    is_day: true,
    humidity_pct: 44,
    wind_mph: 8,
    precip_prob_pct: 10,
    high_f: 78,
    low_f: 61,
    sunrise: "2026-07-01T05:32:00-04:00",
    sunset: "2026-07-01T20:31:00-04:00",
  },
  forecast: forecastFixture(),
});

/** @returns {any[]} Four forecast days; the first is wet (precip line shows). */
function forecastFixture() {
  return [
    { date: "2026-07-02", code: 61, text: "Rain", icon: "wi-rain", high_f: 70, low_f: 58, precip_prob_pct: 80, precip_expected: true },
    { date: "2026-07-03", code: 1, text: "Sunny", icon: "wi-day-sunny", high_f: 82, low_f: 63, precip_prob_pct: 5 },
    { date: "2026-07-04", code: 2, text: "Partly Cloudy", icon: "wi-day-cloudy", high_f: 80, low_f: 62, precip_prob_pct: 10 },
    { date: "2026-07-05", code: 3, text: "Cloudy", icon: "wi-cloudy", high_f: 76, low_f: 60, precip_prob_pct: 20 },
  ];
}

// ── mount ─────────────────────────────────────────────────────────────────────

test("mount: builds the five region containers + the 'Upcoming' heading", () => {
  const app = mountShell();
  for (const id of ["clock", "date", "clock-warn", "current-card", "forecast", "agenda-body", "status"]) {
    assert.ok(doc.getElementById(id), `#${id} exists after mount`);
  }
  assert.ok(app.textContent.includes("Upcoming"), "the hardcoded agenda heading renders");
  // The clock warning starts hidden - shown only when the Pi clock is unsynced.
  assert.equal(doc.getElementById("clock-warn").hidden, true);
});

// ── renderClock ───────────────────────────────────────────────────────────────

test("renderClock: paints 12h time + AM/PM and toggles the sync warning", () => {
  mountShell();
  layout.renderClock(new Date(2026, 0, 5, 13, 5), true);
  const clock = doc.getElementById("clock");
  assert.ok(clock.textContent.includes("1:05"), "13:05 -> 1:05");
  assert.ok(clock.textContent.includes("PM"));
  assert.ok(doc.getElementById("date").textContent.length > 0);
  // synced true -> warning hidden; false -> shown.
  assert.equal(doc.getElementById("clock-warn").hidden, true);
  layout.renderClock(new Date(2026, 0, 5, 13, 6), false);
  assert.equal(doc.getElementById("clock-warn").hidden, false);
  layout.renderClock(new Date(2026, 0, 5, 13, 7), true);
  assert.equal(doc.getElementById("clock-warn").hidden, true);
});

// ── renderCurrent ─────────────────────────────────────────────────────────────

test("renderCurrent: fills the hero from the weather block", () => {
  mountShell();
  layout.renderCurrent(weatherFixture());
  const card = doc.getElementById("current-card");
  const txt = card.textContent;
  assert.ok(txt.includes("72"), "big temp");
  assert.ok(txt.includes("Mostly Sunny"), "condition text");
  assert.ok(txt.includes("78°") && txt.includes("61°"), "hi/lo");
  // The six stat cells: feels-like, rain, wind, humidity, sunrise, sunset.
  assert.equal(withClass(card, "stat").length, 6);
  assert.ok(txt.includes("Feels like") && txt.includes("70°"));
  assert.ok(txt.includes("8 mph") && txt.includes("44%"));
});

// ── renderForecast ────────────────────────────────────────────────────────────

test("renderForecast: renders 4 cards; precip line only on wet days", () => {
  mountShell();
  layout.renderForecast(forecastFixture());
  const root = doc.getElementById("forecast");
  assert.equal(withClass(root, "fcard").length, 4);
  // Exactly one day (the first, precip_expected) shows the precip line.
  assert.equal(withClass(root, "fprecip").length, 1);
  assert.ok(root.textContent.includes("Rain") && root.textContent.includes("80%"));
});

test("renderForecast: slices defensively to 4 even given a longer feed", () => {
  mountShell();
  layout.renderForecast([...forecastFixture(), ...forecastFixture()]);
  assert.equal(withClass(doc.getElementById("forecast"), "fcard").length, 4);
});

// ── renderAgenda: grouping + columns ──────────────────────────────────────────

test("renderAgenda: groups by day — today alone in col1, upcoming days in col2", (t) => {
  freezeNoon(t);
  mountShell();
  const events = [
    timed("Standup", 15, 16), // today
    { start: "2026-07-02", all_day: true, title: "TripDay", kind: "personal" },
    { start: "2026-07-03T10:00:00-04:00", end: "2026-07-03T11:00:00-04:00", all_day: false, title: "Dentist", kind: "personal" },
  ];
  // clientHeight left 0 -> the fit pass is skipped, so grouping is asserted raw.
  layout.renderAgenda(events, true, true);
  const body = doc.getElementById("agenda-body");
  const cols = withClass(body, "agenda-col");
  assert.equal(cols.length, 2, "two columns");
  assert.ok(cols[0].textContent.includes("Today"), "col1 is today");
  assert.ok(cols[0].textContent.includes("Standup"));
  assert.ok(cols[1].textContent.includes("TripDay") && cols[1].textContent.includes("Dentist"));
});

test("renderAgenda: quiet-day 'Nothing today' when today has no personal events (calendar ok)", (t) => {
  freezeNoon(t);
  mountShell();
  layout.renderAgenda([{ start: TODAY, all_day: true, title: "Some Observance", kind: "observance" }], true, true);
  const body = doc.getElementById("agenda-body");
  assert.ok(body.textContent.includes("Nothing today"));
  assert.ok(body.textContent.includes("Some Observance"), "the pill still shows as context");
});

test("renderAgenda: a stale/failed calendar does NOT claim 'Nothing today'", (t) => {
  freezeNoon(t);
  mountShell();
  // calendarOk=false: we don't know today's events, so no emptiness claim.
  layout.renderAgenda([], false, true);
  assert.ok(!doc.getElementById("agenda-body").textContent.includes("Nothing today"));
});

// ── renderAgenda: fit shell (day roll-off + bottom trim) ──────────────────────

test("renderAgenda fit: today overflows -> past rows roll into '+N earlier', bottom into '+N more'", (t) => {
  freezeNoon(t);
  mountShell();
  const events = [
    { start: TODAY, all_day: true, title: "Festival", kind: "observance" }, // pill, never rolls
    timed("Early", 9, 10), // past
    timed("Mid", 11, 12), // past
    timed("Now", 15, 16), // upcoming (next-up)
  ];
  const body = doc.getElementById("agenda-body");
  body._clientHeight = 30; // tiny budget forces the roll-off + trim shell to run
  layout.renderAgenda(events, true, true);
  // planDayFit(90,[10,20,20,20],[f,t,t,f],10,30): both past roll (+2 earlier),
  // then the upcoming row trims off the bottom (+1 more). The pill is protected.
  assert.ok(body.textContent.includes("+2 earlier"), "past rows rolled off");
  assert.ok(body.textContent.includes("+1 more"), "bottom trim summary");
  assert.ok(body.textContent.includes("Festival"), "the pill above the roll-off survives");
  // The roll-off vocabulary means those timed rows are gone from the DOM.
  assert.equal(withClass(body, "event").length, 0);
});

// ── renderAgenda: fit shell (column footer) ───────────────────────────────────

test("renderAgenda fit: col2 overflows -> later days drop into a '+N more days' footer", (t) => {
  freezeNoon(t);
  mountShell();
  const events = [
    timed("TodayEv", 15, 16), // today (col1, protected)
    { start: "2026-07-02", all_day: true, title: "UP2", kind: "personal" },
    { start: "2026-07-03", all_day: true, title: "UP3", kind: "personal" },
    { start: "2026-07-04", all_day: true, title: "UP4", kind: "personal" },
  ];
  const body = doc.getElementById("agenda-body");
  body._clientHeight = 60; // holds one upcoming day-row (40) + footer (10), not all three
  layout.renderAgenda(events, true, true);
  const txt = body.textContent;
  assert.ok(txt.includes("TodayEv"), "col1 today is never dropped");
  assert.ok(txt.includes("UP2"), "first upcoming day kept");
  assert.ok(!txt.includes("UP4") && !txt.includes("UP3"), "later days dropped");
  assert.ok(txt.includes("+2 more days"), "the dropped days are summarized");
});

// ── renderStatus ──────────────────────────────────────────────────────────────

test("renderStatus: happy path — fresh dots + oldest-ok 'Updated' stamp", () => {
  mountShell();
  const data = {
    weather: { ok: true, fetched_at: "2026-07-01T09:40:00-04:00" },
    calendar: { ok: true, fetched_at: "2026-07-01T09:38:00-04:00" },
  };
  layout.renderStatus(data, { refresh: async () => {} });
  const status = doc.getElementById("status");
  const txt = status.textContent;
  assert.ok(txt.includes("Weather") && txt.includes("Calendar"));
  // pickUpdated -> OLDEST ok stamp (09:38), never over-claiming freshness.
  assert.ok(txt.includes("Updated 9:38 AM"));
  assert.equal(withClass(status, "stale").length, 0, "no stale dots when both ok");
  assert.ok(withClass(status, "refresh").length === 1, "refresh control present");
});

test("renderStatus: opts.stale forces all-stale dots and 'Updated —'", () => {
  mountShell();
  layout.renderStatus(null, { stale: true, refresh: async () => {} });
  const status = doc.getElementById("status");
  assert.ok(status.textContent.includes("Updated —"));
  assert.equal(withClass(status, "stale").length, 2, "both source dots go stale");
});

// ── renderUnavailable / cold-boot ─────────────────────────────────────────────

test("renderUnavailable: honest placeholders in every data region (cold boot)", () => {
  mountShell();
  // Cold boot: no data has ever painted -> the core calls renderStatus(null,stale)
  // then renderUnavailable. Nothing should be a blank glass box.
  layout.renderStatus(null, { stale: true, refresh: async () => {} });
  layout.renderUnavailable();
  assert.ok(doc.getElementById("current-card").textContent.includes("Weather unavailable"));
  assert.ok(doc.getElementById("agenda-body").textContent.includes("Data unavailable"));
  assert.ok(doc.getElementById("status").textContent.includes("Updated —"));
  // The forecast row is cleared rather than placeheld (matches the monolith).
  assert.equal(doc.getElementById("forecast").children.length, 0);
});

// t.mock.timers auto-reset per test; reset the top-level mock too for safety.
test.after(() => mock.timers.reset());
