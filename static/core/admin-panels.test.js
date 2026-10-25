// Unit tests for core/admin-panels.js - the shared admin panel DOM. Run with
// `node --test` from static/.
//
// Drives the builders against a tiny local DOM stub (just the surface
// admin-panels.js touches), like the layout suites do.

import test from "node:test";
import assert from "node:assert/strict";

import { configPanel, transitionScrim } from "./admin-panels.js";

// ── minimal DOM stub (local, dep-free) ────────────────────────────────────────

class El {
  /** @param {string} tag */
  constructor(tag) {
    this.tagName = tag;
    /** @type {any[]} */
    this.children = [];
    /** @type {Set<string>} */
    this._classes = new Set();
    /** @type {Record<string, string>} */
    this.attrs = {};
    /** @type {Record<string, (() => void)[]>} */
    this.listeners = {};
    this.disabled = false;
    this._text = "";
    const self = this;
    this.classList = {
      /** @param {...string} cs */
      add: (...cs) => cs.forEach((c) => self._classes.add(c)),
      /** @param {string} c */
      contains: (c) => self._classes.has(c),
    };
  }
  set className(v) {
    this._classes = new Set(String(v).split(/\s+/).filter(Boolean));
  }
  get className() {
    return [...this._classes].join(" ");
  }
  set textContent(v) {
    this._text = String(v);
    this.children = [];
  }
  get textContent() {
    return this._text + this.children.map((c) => (typeof c === "string" ? c : c.textContent)).join("");
  }
  /** @param {...any} nodes */
  append(...nodes) {
    this.children.push(...nodes);
  }
  /** @param {string} k @param {string} v */
  setAttribute(k, v) {
    this.attrs[k] = v;
  }
  /** @param {string} type @param {() => void} fn */
  addEventListener(type, fn) {
    (this.listeners[type] ??= []).push(fn);
  }
  click() {
    if (!this.disabled) (this.listeners.click ?? []).forEach((fn) => fn());
  }
}

globalThis.document = /** @type {any} */ ({ createElement: (/** @type {string} */ t) => new El(t) });

/** Depth-first: every element under `node` (inclusive) carrying `cls`. */
function withClass(/** @type {any} */ node, /** @type {string} */ cls) {
  /** @type {any[]} */
  const out = [];
  const walk = (/** @type {any} */ n) => {
    if (typeof n === "string") return;
    if (n._classes.has(cls)) out.push(n);
    n.children.forEach(walk);
  };
  walk(node);
  return out;
}

const root = (/** @type {any[]} */ nodes) => Object.assign(new El("div"), { children: nodes });

// ── fixtures ──────────────────────────────────────────────────────────────────

const CONFIG = {
  layout: { current: "classic", options: ["classic", "hud", "swiss-mono"] },
  theme: { current: "", options: ["", "nord"] },
  icon_pack: { current: "weather-icons", options: ["weather-icons"] },
};

/** @param {any} [over] */
const view = (over = {}) => ({ config: CONFIG, staged: {}, pending: 0, busy: false, notice: null, ...over });

function fakeCtx() {
  /** @type {any[]} */
  const calls = [];
  return {
    calls,
    back: () => calls.push(["back"]),
    /** @param {string} k @param {string} v */
    stage: (k, v) => calls.push(["stage", k, v]),
    apply: () => calls.push(["apply"]),
    dismiss: () => calls.push(["dismiss"]),
  };
}

/** The option buttons of the knob named `name`. */
function opts(/** @type {any} */ panel, /** @type {string} */ name) {
  const knob = withClass(panel, "admin-knob").find((k) => withClass(k, "admin-knob-name")[0].textContent === name);
  return withClass(knob, "admin-opt");
}

// ── config panel ──────────────────────────────────────────────────────────────

test("configPanel: one knob per setting, each listing every option, live value marked", () => {
  const panel = root(configPanel(view(), fakeCtx()));
  const names = withClass(panel, "admin-knob-name").map((n) => n.textContent);
  assert.deepEqual(names, ["Layout", "Theme", "Icon pack"]);
  const layout = opts(panel, "Layout");
  assert.deepEqual(layout.map((o) => o.textContent), ["classic", "hud", "swiss-mono"]);
  assert.deepEqual(withClass(panel, "admin-current").map((o) => o.textContent), ["classic", "default", "weather-icons"]);
  assert.equal(withClass(panel, "admin-knob-live")[0].textContent, "Live: classic");
});

test("configPanel: the built-in palette (THEME '') reads as 'default'", () => {
  const panel = root(configPanel(view(), fakeCtx()));
  assert.deepEqual(opts(panel, "Theme").map((o) => o.textContent), ["default", "nord"]);
});

test("configPanel: a staged value is marked and the live one demoted", () => {
  const panel = root(configPanel(view({ staged: { theme: "nord" }, pending: 1 }), fakeCtx()));
  const [def, nord] = opts(panel, "Theme");
  assert.ok(def.classList.contains("admin-was-current"));
  assert.ok(!def.classList.contains("admin-current"));
  assert.ok(nord.classList.contains("admin-staged"));
  assert.equal(nord.attrs["aria-pressed"], "true");
  assert.equal(def.attrs["aria-pressed"], "false");
});

test("configPanel: tapping an option stages it", () => {
  const ctx = fakeCtx();
  const panel = root(configPanel(view(), ctx));
  opts(panel, "Layout")[1].click();
  assert.deepEqual(ctx.calls, [["stage", "layout", "hud"]]);
});

test("configPanel: Apply is off with nothing staged, on with a change", () => {
  const ctx = fakeCtx();
  const idle = withClass(root(configPanel(view(), ctx)), "admin-apply-btn")[0];
  assert.equal(idle.disabled, true);
  idle.click();
  assert.equal(ctx.calls.length, 0);

  const panel = root(configPanel(view({ staged: { layout: "hud" }, pending: 1 }), ctx));
  const btn = withClass(panel, "admin-apply-btn")[0];
  assert.equal(btn.disabled, false);
  assert.ok(btn.classList.contains("admin-on"));
  assert.equal(withClass(panel, "admin-apply-summary")[0].textContent, "1 change staged");
  btn.click();
  assert.deepEqual(ctx.calls, [["apply"]]);
});

test("configPanel: everything is inert while busy", () => {
  const ctx = fakeCtx();
  const panel = root(configPanel(view({ staged: { layout: "hud" }, pending: 1, busy: true }), ctx));
  withClass(panel, "admin-opt").forEach((o) => o.click());
  withClass(panel, "admin-apply-btn")[0].click();
  assert.equal(ctx.calls.length, 0);
});

test("configPanel: a notice replaces the summary; an error is flagged", () => {
  const panel = root(configPanel(view({ notice: { kind: "error", text: "unknown layout" } }), fakeCtx()));
  const sum = withClass(panel, "admin-apply-summary")[0];
  assert.equal(sum.textContent, "unknown layout");
  assert.ok(sum.classList.contains("admin-is-error"));
});

test("configPanel: no config renders a message instead of knobs", () => {
  const loading = root(configPanel(view({ config: null }), fakeCtx()));
  assert.equal(withClass(loading, "admin-knob").length, 0);
  assert.equal(loading.textContent, "Loading…");
  const down = root(configPanel(view({ config: null, notice: { kind: "error", text: "Settings unavailable" } }), fakeCtx()));
  assert.equal(down.textContent, "Settings unavailable");
});

// ── transition overlay ────────────────────────────────────────────────────────

test("transitionScrim: null clears (no overlay)", () => {
  assert.equal(transitionScrim(null, undefined, fakeCtx()), null);
});

test("transitionScrim: applying shows a spinner and the reload promise", () => {
  const scrim = transitionScrim("applying", undefined, fakeCtx());
  assert.equal(withClass(scrim, "admin-spin").length, 1);
  assert.match(scrim.textContent, /Restarting dashboard/);
});

test("transitionScrim: error shows the reason and a way back to the panels", () => {
  const ctx = fakeCtx();
  const scrim = transitionScrim("error", "The dashboard did not come back healthy.", ctx);
  assert.equal(withClass(scrim, "admin-spin").length, 0);
  assert.match(scrim.textContent, /did not come back healthy/);
  withClass(scrim, "admin-dbtn")[0].click();
  assert.deepEqual(ctx.calls, [["dismiss"]]);
});
