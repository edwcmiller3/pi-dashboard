// Behavioral tests for the swiss-mono layout's DOM renderers, fit shells, and
// degrade paths. Run with Node's built-in runner (no deps):  node --test  (from static/)
//
// Mirrors classic.test.js: the layout is the only piece of the module graph that
// touches the DOM, so it is exercised against a tiny, dependency-free DOM stub
// defined locally below - just enough of the surface index.js uses. The pure fit
// PLANNERS (planDayFit/planColumnFit) are unit-tested in ../../app.test.js; here
// we prove the imperative SHELL wires real measurements into the plan and applies
// it to the DOM (inserts "+N earlier"/"+N more"/"+N more days", removes children).
//
// Typing mirrors classic.test.js: JSDoc typedefs document the fixtures but
// `// @ts-check` is intentionally off. Clock-dependent tests freeze time via
// `t.mock.timers` so the "today awareness" logic can't flake across local midnight.

import test, { mock } from "node:test";
import assert from "node:assert/strict";

// ── minimal DOM stub (local, dep-free) ────────────────────────────────────────

// Leaf render height (px) every element with no ELEMENT children reports; a
// container's height is the sum of its element children's heights, so removals
// compose linearly - the invariant the fit planners assume (see core/agenda.js).
const LEAF_H = 10;

/** A stub Element: only the surface swiss-mono/index.js exercises. */
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
  // Capture handlers so tests can drive them (tap→click); mirrors hud.test.js's
  // stub (records listeners, fired via the `fire()` helper).
  /** @param {string} type @param {() => void} fn */
  addEventListener(type, fn) {
    (this._listeners ??= {})[type] ??= [];
    this._listeners[type].push(fn);
  }

  /** @param {string} sel @returns {El | null} */
  querySelector(sel) {
    return queryOne(this, sel);
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

/**
 * querySelector supporting a descendant chain ("#status .refresh") as well as a
 * single simple selector. Each space-separated part is resolved as a descendant
 * of the previous match - just enough for the compound selector the refresh
 * spin/error helpers use (`document.querySelector("#status .refresh")`).
 * @param {El} root @param {string} sel @returns {El | null}
 */
function queryOne(root, sel) {
  let scope = root;
  for (const part of sel.trim().split(/\s+/)) {
    const hit = find(scope, matcher(part));
    if (!hit) return null;
    scope = hit;
  }
  return scope === root ? null : scope;
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
  querySelector: (sel) => (doc._appRoot ? queryOne(doc._appRoot, sel) : null),
};

// index.js + core/dom.js reach the DOM through the global `document`; wire the
// stub in before any test runs (module top level runs before tests).
globalThis.document = /** @type {any} */ (doc);

// measureLine() in index.js adds getComputedStyle(probe).marginTop back onto the
// column footer's measured height, because the real `.agenda-more.days` footer
// carries a 26px top margin (layout.css) that getBoundingClientRect excludes.
// Stub it so that path actually runs: a `.days` probe reports the real 26px, any
// other node reports 0px - so the plain day-level "+N …" probes are unaffected
// and the existing roll-off tests keep their arithmetic.
globalThis.getComputedStyle = /** @type {any} */ (
  (node) => ({ marginTop: node.classList && node.classList.contains("days") ? "26px" : "0px" })
);

// The layout under test - imported AFTER the global is set.
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

/** Synthesize a DOM event by invoking the handlers the stub captured (tap→click). @param {El} node @param {string} type */
function fire(node, type) {
  for (const fn of node._listeners?.[type] ?? []) fn();
}

/** Freeze the clock at local noon on 2026-07-01. @param {any} t */
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

test("mount: builds the region containers + starts the clock warning hidden", () => {
  const app = mountShell();
  for (const id of ["clock", "clock-date", "clock-warn", "current", "forecast", "agenda-body", "status"]) {
    assert.ok(doc.getElementById(id), `#${id} exists after mount`);
  }
  assert.ok(app.textContent.includes("Upcoming"), "the static agenda tag renders");
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
  assert.ok(doc.getElementById("clock-date").textContent.length > 0);
  // synced true -> warning hidden; false -> shown.
  assert.equal(doc.getElementById("clock-warn").hidden, true);
  layout.renderClock(new Date(2026, 0, 5, 13, 6), false);
  assert.equal(doc.getElementById("clock-warn").hidden, false);
  layout.renderClock(new Date(2026, 0, 5, 13, 7), true);
  assert.equal(doc.getElementById("clock-warn").hidden, true);
});

// ── renderCurrent ─────────────────────────────────────────────────────────────

test("renderCurrent: fills the hero temp + condition + all 8 meta cells", () => {
  mountShell();
  layout.renderCurrent(weatherFixture());
  const card = doc.getElementById("current");
  const txt = card.textContent;
  assert.ok(txt.includes("72"), "big temp");
  assert.ok(txt.includes("Mostly Sunny"), "condition text");
  // swiss-mono puts High/Low IN the meta grid (unlike classic's hero-side stack).
  assert.equal(withClass(card, "meta-item").length, 8, "eight meta cells");
  assert.ok(txt.includes("High") && txt.includes("78°"), "High cell");
  assert.ok(txt.includes("Low") && txt.includes("61°"), "Low cell");
  assert.ok(txt.includes("Feels like") && txt.includes("70°"));
  assert.ok(txt.includes("Rain") && txt.includes("10%"));
  assert.ok(txt.includes("Humidity") && txt.includes("44%"));
  assert.ok(txt.includes("Wind") && txt.includes("8 mph"));
  assert.ok(txt.includes("Sunrise") && txt.includes("5:32a"), "sunrise via localParts");
  assert.ok(txt.includes("Sunset") && txt.includes("8:31p"), "sunset via localParts");
});

// ── renderForecast ────────────────────────────────────────────────────────────

test("renderForecast: renders 4 cells; precip line only on wet days", () => {
  mountShell();
  layout.renderForecast(forecastFixture());
  const root = doc.getElementById("forecast");
  assert.equal(withClass(root, "fc").length, 4);
  // Exactly one day (the first, precip_expected) shows the precip line.
  assert.equal(withClass(root, "fc-precip").length, 1);
  assert.ok(root.textContent.includes("Rain") && root.textContent.includes("80%"));
});

test("renderForecast: slices defensively to 4 even given a longer feed", () => {
  mountShell();
  layout.renderForecast([...forecastFixture(), ...forecastFixture()]);
  assert.equal(withClass(doc.getElementById("forecast"), "fc").length, 4);
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
  const cols = withClass(body, "ag-col");
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
  // The holiday/observance renders as a header pill (context), not a row.
  assert.equal(withClass(body, "pill").length, 1, "observance shows as a pill");
  assert.ok(body.textContent.includes("Some Observance"));
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
    { start: TODAY, all_day: true, title: "Festival", kind: "observance" }, // header pill, never rolls
    timed("Early", 9, 10), // past
    timed("Mid", 11, 12), // past
    timed("Now", 15, 16), // upcoming (next-up -> "● NOW" row)
  ];
  const body = doc.getElementById("agenda-body");
  body._clientHeight = 55; // tiny budget forces the roll-off + trim shell to run
  layout.renderAgenda(events, true, true);
  const txt = body.textContent;
  assert.ok(txt.includes("+2 earlier"), "past rows rolled off");
  assert.ok(txt.includes("+1 more"), "bottom trim summary");
  assert.ok(txt.includes("Festival"), "the header pill above the roll-off survives");
  // The roll-off vocabulary means those timed rows are gone from the DOM.
  assert.equal(withClass(body, "ev").length, 0);
});

// ── renderAgenda: next-up NOW row ─────────────────────────────────────────────

test("renderAgenda: the next-up timed event today gets the '● NOW' row", (t) => {
  freezeNoon(t);
  mountShell();
  // clientHeight 0 -> no fit pass, so the emphasized row is asserted raw.
  layout.renderAgenda([timed("Past", 9, 10), timed("Focus block", 15, 16)], true, true);
  const body = doc.getElementById("agenda-body");
  const nowRows = withClass(body, "ev").filter((r) => r._classes.has("now"));
  assert.equal(nowRows.length, 1, "exactly one NOW row");
  assert.ok(nowRows[0].textContent.includes("Focus block"), "the soonest not-past timed event");
  assert.ok(nowRows[0].textContent.includes("● NOW"), "carries the NOW tag");
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
  // Holds one upcoming day-block (40) + the footer's OUTER box (10 + its 26px
  // `.days` margin = 36), i.e. 76 - not all three days. The margin term is real
  // now that getComputedStyle is stubbed (see measureLine); pre-fix this was 60.
  body._clientHeight = 76;
  layout.renderAgenda(events, true, true);
  const txt = body.textContent;
  assert.ok(txt.includes("TodayEv"), "col1 today is never dropped");
  assert.ok(txt.includes("UP2"), "first upcoming day kept");
  assert.ok(!txt.includes("UP4") && !txt.includes("UP3"), "later days dropped");
  assert.ok(txt.includes("+2 more days"), "the dropped days are summarized");
});

// ── renderStatus ──────────────────────────────────────────────────────────────

test("renderStatus: happy path — fresh squares + oldest-ok 'Updated' stamp", () => {
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
  assert.equal(withClass(status, "st-sq").filter((n) => n._classes.has("stale")).length, 0, "no stale squares when both ok");
  assert.equal(withClass(status, "refresh").length, 1, "refresh control present");
});

test("renderStatus: opts.stale forces stale squares and 'Updated —'", () => {
  mountShell();
  layout.renderStatus(null, { stale: true, refresh: async () => {} });
  const status = doc.getElementById("status");
  assert.ok(status.textContent.includes("Updated —"));
  assert.equal(withClass(status, "st-sq").filter((n) => n._classes.has("stale")).length, 2, "both source squares go stale");
});

// ── renderUnavailable / cold-boot ─────────────────────────────────────────────

test("renderUnavailable: honest placeholders in every region (cold boot)", () => {
  mountShell();
  // Cold boot: the core calls renderStatus(null,stale) then renderUnavailable.
  layout.renderStatus(null, { stale: true, refresh: async () => {} });
  layout.renderUnavailable();
  assert.ok(doc.getElementById("current").textContent.includes("Weather unavailable"));
  assert.ok(doc.getElementById("forecast").textContent.includes("Forecast unavailable"));
  assert.ok(doc.getElementById("agenda-body").textContent.includes("Data unavailable"));
  assert.ok(doc.getElementById("status").textContent.includes("Updated —"));
});

// ── renderAgenda fit: footer margin no-clip regression guard ──────────────────

test("renderAgenda fit: col2 reserves the footer's 26px margin so nothing clips (regression guard)", (t) => {
  // GUARD for the measureLine fix. The column footer is `.agenda-more.days`, whose
  // layout.css `margin-top:26px` is EXCLUDED by getBoundingClientRect. measureLine
  // must add getComputedStyle(probe).marginTop back; otherwise the column reserves
  // 26px too little and the last kept day clips under the tile's overflow:hidden.
  //
  // Budget 100 is decision-flipping. Reserving the whole footer (10 + 26 = 36) keeps
  // ONE upcoming day ("+2 more days", occupied 40 + 36 = 76 ≤ 100 - no clip). The old
  // bug - measuring a plain `agenda-more` probe (10) - would keep TWO days ("+1 more
  // day", occupied 40 + 40 + 36 = 116 > 100 - clip). So if measureLine reverts to a
  // plain probe (drops the getComputedStyle margin term), this test goes red on both
  // the kept-count and the footer label.
  freezeNoon(t);
  mountShell();
  const events = [
    timed("TodayEv", 15, 16), // col1 today - protected, never dropped
    { start: "2026-07-02", all_day: true, title: "UP2", kind: "personal" },
    { start: "2026-07-03", all_day: true, title: "UP3", kind: "personal" },
    { start: "2026-07-04", all_day: true, title: "UP4", kind: "personal" },
  ];
  const body = doc.getElementById("agenda-body");
  body._clientHeight = 100;
  layout.renderAgenda(events, true, true);

  const col2 = withClass(body, "ag-col-body")[1];
  const kept = withClass(col2, "ag-block");
  assert.equal(kept.length, 1, "with the 26px margin reserved, only one upcoming day fits");
  const footer = withClass(col2, "agenda-more").find((n) => n._classes.has("days"));
  assert.ok(footer, "the column '+N more days' footer is present");
  assert.ok(footer.textContent.includes("+2 more days"), "and summarizes BOTH dropped days");

  // No overflow: kept day-blocks + the footer's OUTER box (rect height + its 26px top
  // margin, which getBoundingClientRect omits) must stay within the tile budget.
  const footerOuter =
    footer.getBoundingClientRect().height + parseFloat(getComputedStyle(footer).marginTop);
  const occupied = kept.reduce((sum, b) => sum + b.getBoundingClientRect().height, 0) + footerOuter;
  assert.ok(occupied <= 100, `column content (${occupied}px) fits the 100px tile`);
});

// ── renderStatus: manual refresh state machine ────────────────────────────────

/** @returns {any} A both-ok status doc for the refresh tests. */
const statusData = () => ({
  weather: { ok: true, fetched_at: "2026-07-01T09:40:00-04:00" },
  calendar: { ok: true, fetched_at: "2026-07-01T09:38:00-04:00" },
});

test("renderStatus refresh: click spins, double-tap is guarded, spin clears once settled", async () => {
  mountShell();
  let calls = 0;
  /** @type {() => void} */
  let release = () => {};
  const gate = new Promise((r) => { release = r; });
  layout.renderStatus(statusData(), { refresh: async () => { calls++; await gate; } });
  const refresh = withClass(doc.getElementById("status"), "refresh")[0];
  assert.ok(refresh, "refresh control present");

  fire(refresh, "click");
  assert.ok(refresh._classes.has("is-spinning"), "spins while the refresh is in flight");
  fire(refresh, "click"); // double-tap while refreshing → ignored by the `refreshing` guard
  release();
  await new Promise((r) => setImmediate(r)); // let the awaited refresh settle
  assert.equal(calls, 1, "double-tap guarded — the core refresh ran exactly once");
  // Re-query: renderStatus re-mounts the node on repaint, so read the live one.
  const after = withClass(doc.getElementById("status"), "refresh")[0];
  assert.ok(!after._classes.has("is-spinning"), "spin clears in the finally once refresh settles");
});

test("renderStatus refresh: a rejected refresh flashes is-error, then clears after 1500ms", async (t) => {
  t.mock.timers.enable({ apis: ["setTimeout"] });
  t.mock.method(console, "error", () => {}); // the SUT logs the failure - expected, silence it
  mountShell();
  layout.renderStatus(statusData(), { refresh: async () => { throw new Error("boom"); } });
  const refresh = withClass(doc.getElementById("status"), "refresh")[0];

  fire(refresh, "click");
  await new Promise((r) => setImmediate(r)); // let the rejection propagate + flashRefreshError run
  assert.ok(refresh._classes.has("is-error"), "failed refresh flashes the control red");
  t.mock.timers.tick(1500);
  assert.ok(!refresh._classes.has("is-error"), "error clears after the 1500ms timeout");
});

// ── roll-off glyph emission (↑ / ↓ as real text, per test_swiss_fonts.py) ─────

test("roll-off glyphs: ↑ on 'earlier', ↓ on the day '+N more' and the column '+N more days'", (t) => {
  freezeNoon(t);
  // Scenario A (col1 day-level roll-off): today overflows → an ↑ "earlier" line and
  // a ↓ "more" line (mirrors the existing budget-55 fit test).
  mountShell();
  const bodyA = doc.getElementById("agenda-body");
  bodyA._clientHeight = 55;
  layout.renderAgenda(
    [
      { start: TODAY, all_day: true, title: "Festival", kind: "observance" },
      timed("Early", 9, 10), // past
      timed("Mid", 11, 12), // past
      timed("Now", 15, 16), // upcoming
    ],
    true,
    true,
  );
  const linesA = withClass(bodyA, "agenda-more");
  const earlier = linesA.find((n) => n.textContent.includes("earlier"));
  const more = linesA.find((n) => n.textContent.includes("more") && !n.textContent.includes("days"));
  assert.ok(earlier && earlier.textContent.includes("↑"), "the '+N earlier' line carries ↑ (U+2191) as text");
  assert.ok(more && more.textContent.includes("↓"), "the day '+N more' line carries ↓ (U+2193) as text");

  // Scenario B (col2 column-level drop): later upcoming days drop → a ↓ "+N more
  // days" footer. Needs the wider budget so the footer itself fits.
  mountShell();
  const bodyB = doc.getElementById("agenda-body");
  bodyB._clientHeight = 100;
  layout.renderAgenda(
    [
      timed("TodayEv", 15, 16),
      { start: "2026-07-02", all_day: true, title: "UP2", kind: "personal" },
      { start: "2026-07-03", all_day: true, title: "UP3", kind: "personal" },
      { start: "2026-07-04", all_day: true, title: "UP4", kind: "personal" },
    ],
    true,
    true,
  );
  const footer = withClass(bodyB, "agenda-more").find((n) => n._classes.has("days"));
  assert.ok(footer && footer.textContent.includes("↓"), "the column '+N more days' footer carries ↓ as text");
  assert.ok(footer.textContent.includes("more day"), "and it is the column footer (not a day-level line)");
});

// ── renderCurrent: date-only sunrise/sunset defensive branch ──────────────────

test("renderCurrent: date-only sunrise/sunset (localParts.time null) render '—'", () => {
  mountShell();
  const w = weatherFixture();
  // Contract drift: a date-only value → localParts(...).time is null → fmtCompactOr
  // takes its null arm and renders an em-dash rather than crashing.
  w.current.sunrise = "2026-07-01";
  w.current.sunset = "2026-07-01";
  layout.renderCurrent(w);
  const cells = withClass(doc.getElementById("current"), "meta-item");
  const valueFor = (key) => {
    const cell = cells.find((c) => withClass(c, "meta-k")[0].textContent === key);
    return withClass(cell, "meta-v")[0].textContent;
  };
  assert.equal(valueFor("Sunrise"), "—", "Sunrise falls back to em-dash");
  assert.equal(valueFor("Sunset"), "—", "Sunset falls back to em-dash");
});

// ── renderAgenda: info-kind marker row ────────────────────────────────────────

test("renderAgenda: an info-kind item renders as a .marker line carrying its title", (t) => {
  freezeNoon(t);
  mountShell();
  // clientHeight 0 → no fit pass; the marker row is asserted raw.
  layout.renderAgenda(
    [
      timed("Standup", 15, 16), // a personal event so today isn't a quiet day
      { start: `${TODAY}T02:00:00-04:00`, all_day: false, title: "DST ends — clocks back", kind: "info" },
    ],
    true,
    true,
  );
  const body = doc.getElementById("agenda-body");
  const markers = withClass(body, "marker");
  assert.equal(markers.length, 1, "the info item renders as a single marker line");
  assert.ok(markers[0].textContent.includes("DST ends"), "the marker carries its title as text");
  // An info row is NOT an event row (no next-up/roll-off eligibility).
  assert.equal(withClass(markers[0], "ev-nowtag").length, 0, "info markers never get the NOW tag");
});

// ── renderForecast empty + weather-icon class pass-through ─────────────────────

test("renderForecast([]) makes zero cards without throwing; renderCurrent passes the icon class through", () => {
  mountShell();
  assert.doesNotThrow(() => layout.renderForecast([]), "an empty feed renders no cards, no crash");
  assert.equal(withClass(doc.getElementById("forecast"), "fc").length, 0, "no .fc cards for an empty feed");

  layout.renderCurrent(weatherFixture());
  const wi = withClass(doc.getElementById("current"), "wi")[0];
  assert.ok(wi, "the current-weather .wi glyph node exists");
  assert.ok(wi._classes.has("wi-day-sunny"), "the resolved icon class (c.icon) passes onto the .wi node");
});

// t.mock.timers auto-reset per test; reset the top-level mock too for safety.
test.after(() => mock.timers.reset());
