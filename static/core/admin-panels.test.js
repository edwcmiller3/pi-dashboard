// Unit tests for core/admin-panels.js, against a minimal local DOM stub.

import test from "node:test";
import assert from "node:assert/strict";

import { actionsPanel, configPanel, confirmDialog, healthPanel, transitionScrim } from "./admin-panels.js";

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
    /** @param {string} a */
    request: (a) => calls.push(["request", a]),
    confirm: () => calls.push(["confirm"]),
    cancel: () => calls.push(["cancel"]),
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

// ── health panel ──────────────────────────────────────────────────────────────

const gib = (/** @type {number} */ n) => Math.round(n * 2 ** 30);

/** The CONTENT.md nominal fixture, on a Pi. @param {any} [over] */
const stats = (over = {}) => ({
  cpu_percent: 22,
  memory: { used: gib(1.4), total: gib(3.8) },
  disk: { used: gib(4.1), total: gib(29) },
  uptime_s: 8 * 3600 + 46 * 60 + 12,
  host: "raspberrypi",
  temp_c: 48.3,
  throttle: { raw: "0x0", flags: [] },
  network: { iface: "wlan0", ip: "192.168.1.42", netmask: "255.255.255.0", prefix: 24 },
  ...over,
});

/** label -> metric node */
function metrics(/** @type {any[]} */ nodes) {
  return new Map(withClass(root(nodes), "admin-metric").map((m) => [withClass(m, "admin-k")[0].textContent, m]));
}
const value = (/** @type {any} */ m) => withClass(m, "admin-v")[0].textContent;

test("healthPanel: the nominal fixture renders every metric as the mock shows it", () => {
  const m = metrics(healthPanel(stats()));
  assert.deepEqual([...m.keys()], ["CPU", "RAM", "Temp", "Disk", "Uptime", "Host", "Throttle", "Network"]);
  assert.equal(value(m.get("CPU")), "22%");
  assert.equal(value(m.get("RAM")), "1.4 / 3.8 GB");
  assert.equal(value(m.get("Temp")), "48.3 °C");
  assert.equal(value(m.get("Disk")), "4.1 / 29 GB");
  assert.equal(value(m.get("Uptime")), "8h 46m");
  assert.equal(value(m.get("Host")), "raspberrypi");
  assert.equal(value(m.get("Network")), "192.168.1.42 /24 · wlan0");
  assert.equal(withClass(root(healthPanel(stats())), "admin-is-warn").length, 0);
});

test("healthPanel: healthy throttle reads 'No throttling' with the raw hex beside it", () => {
  const t = metrics(healthPanel(stats())).get("Throttle");
  const [flag] = withClass(t, "admin-flag");
  assert.equal(flag.textContent, "No throttling");
  assert.ok(flag.classList.contains("admin-ok"));
  assert.equal(withClass(t, "admin-hex")[0].textContent, "0x0");
});

test("healthPanel: off-Pi, temp and throttle read 'unavailable' and nothing else breaks", () => {
  const m = metrics(healthPanel(stats({ temp_c: null, throttle: null })));
  for (const k of ["Temp", "Throttle"]) {
    assert.equal(value(m.get(k)), "unavailable");
    assert.ok(m.get(k).classList.contains("admin-unavail"));
  }
  assert.equal(value(m.get("CPU")), "22%");
});

test("healthPanel: every field null still renders all eight tiles, each unavailable", () => {
  const nulls = Object.fromEntries(Object.keys(stats()).map((k) => [k, null]));
  const m = metrics(healthPanel(/** @type {any} */ (nulls)));
  assert.equal(m.size, 8);
  assert.ok([...m.values()].every((x) => value(x) === "unavailable"));
});

test("healthPanel: the degraded fixture flags CPU, RAM, temp and disk, not uptime", () => {
  const m = metrics(
    healthPanel(
      stats({ cpu_percent: 96, memory: { used: gib(3.6), total: gib(3.8) }, temp_c: 82.4, disk: { used: gib(27.3), total: gib(29) } }),
    ),
  );
  for (const k of ["CPU", "RAM", "Temp", "Disk"]) assert.ok(m.get(k).classList.contains("admin-is-warn"), k);
  assert.ok(!m.get("Uptime").classList.contains("admin-is-warn"));
  assert.equal(value(m.get("RAM")), "3.6 / 3.8 GB");
  assert.equal(value(m.get("Disk")), "27.3 / 29 GB");
});

test("healthPanel: 0x50005 decodes to named flags, 'now & earlier', never hex alone", () => {
  const throttle = {
    raw: "0x50005",
    flags: [
      { flag: "under-voltage", now: true, occurred: true },
      { flag: "throttled", now: true, occurred: true },
    ],
  };
  const t = metrics(healthPanel(stats({ throttle }))).get("Throttle");
  const flags = withClass(t, "admin-flag");
  assert.deepEqual(
    flags.map((f) => f.textContent),
    ["Under-voltage", "Throttled", "now & earlier"],
  );
  assert.ok(flags[0].classList.contains("admin-bad") && flags[1].classList.contains("admin-bad"));
  assert.ok(flags[2].classList.contains("admin-muted"));
  assert.equal(withClass(t, "admin-hex")[0].textContent, "0x50005");
});

test("healthPanel: mixed throttle history qualifies each flag on its own", () => {
  const throttle = {
    raw: "0x50001",
    flags: [
      { flag: "under-voltage", now: true, occurred: true },
      { flag: "throttled", now: false, occurred: true },
    ],
  };
  const t = metrics(healthPanel(stats({ throttle }))).get("Throttle");
  assert.deepEqual(
    withClass(t, "admin-flag").map((f) => f.textContent),
    ["Under-voltage · now & earlier", "Throttled · earlier"],
  );
});

test("healthPanel: uptime scales from minutes to days", () => {
  const up = (/** @type {number} */ s) => value(metrics(healthPanel(stats({ uptime_s: s }))).get("Uptime"));
  assert.equal(up(59), "0m");
  assert.equal(up(25 * 60), "25m");
  assert.equal(up(3 * 86400 + 4 * 3600 + 5 * 60), "3d 4h");
});

test("healthPanel: a network without a usable netmask still shows the address", () => {
  const network = { iface: "eth0", ip: "10.0.0.5", netmask: null, prefix: null };
  assert.equal(value(metrics(healthPanel(stats({ network }))).get("Network")), "10.0.0.5 · eth0");
});

test("healthPanel: a failed poll (null) renders one unavailable message", () => {
  const nodes = healthPanel(null);
  assert.equal(nodes.length, 1);
  assert.ok(nodes[0].classList.contains("admin-empty"));
  assert.match(nodes[0].textContent, /unavailable/i);
});

// ── device actions + confirm dialog ──────────────────────────────────────────

/** @param {any} [over] */
const actions = (over = {}) => ({ reboot: true, confirming: null, busy: false, error: null, ...over });

/** label -> action button */
function acts(/** @type {any[]} */ nodes) {
  return new Map(withClass(root(nodes), "admin-act").map((b) => [withClass(b, "admin-lbl")[0].textContent, b]));
}

test("actionsPanel: Restart and Reboot, each tap only asks to confirm", () => {
  const ctx = fakeCtx();
  const btns = acts(actionsPanel(actions(), ctx));
  assert.deepEqual([...btns.keys()], ["Restart dashboard", "Reboot Pi"]);
  assert.ok(btns.get("Reboot Pi")._classes.has("admin-danger"));
  assert.ok(!btns.get("Restart dashboard")._classes.has("admin-danger"));
  btns.get("Restart dashboard").click();
  btns.get("Reboot Pi").click();
  assert.deepEqual(ctx.calls, [["request", "restart"], ["request", "reboot"]]);
});

test("actionsPanel: reboot is disabled and says so when unavailable; restart still works", () => {
  const btns = acts(actionsPanel(actions({ reboot: false }), fakeCtx()));
  assert.equal(btns.get("Reboot Pi").disabled, true);
  assert.equal(withClass(btns.get("Reboot Pi"), "admin-act-note")[0].textContent, "unavailable");
  assert.equal(btns.get("Restart dashboard").disabled, false);
});

test("actionsPanel: reboot waits, disabled, while availability is still unknown", () => {
  const btns = acts(actionsPanel(actions({ reboot: null }), fakeCtx()));
  assert.equal(btns.get("Reboot Pi").disabled, true);
  assert.equal(withClass(btns.get("Reboot Pi"), "admin-act-note").length, 0);
});

test("actionsPanel: inert while an action is in flight", () => {
  const btns = acts(actionsPanel(actions({ busy: true }), fakeCtx()));
  assert.ok([...btns.values()].every((b) => b.disabled));
});

test("actionsPanel: the last failure is shown, flagged as an error", () => {
  const nodes = actionsPanel(actions({ error: "the restart failed" }), fakeCtx());
  const [err] = withClass(root(nodes), "admin-act-error");
  assert.equal(err.textContent, "the restart failed");
  assert.equal(withClass(root(actionsPanel(actions(), fakeCtx())), "admin-act-error").length, 0);
});

test("confirmDialog: nothing pending, no dialog", () => {
  assert.equal(confirmDialog(actions(), fakeCtx()), null);
});

test("confirmDialog: reboot asks as the mock does; Cancel cancels, Reboot confirms", () => {
  const ctx = fakeCtx();
  const scrim = confirmDialog(actions({ confirming: "reboot" }), ctx);
  assert.ok(scrim);
  assert.equal(scrim.attrs.role, "alertdialog");
  assert.match(scrim.textContent, /Reboot the Pi\?/);
  assert.match(scrim.textContent, /dark for about 40 seconds/);
  const [cancel, go] = withClass(scrim, "admin-dbtn");
  assert.equal(cancel.textContent, "Cancel");
  assert.equal(go.textContent, "Reboot");
  assert.ok(go._classes.has("admin-danger"));
  cancel.click();
  go.click();
  assert.deepEqual(ctx.calls, [["cancel"], ["confirm"]]);
});

test("confirmDialog: restart names what it does and that the Pi stays up", () => {
  const scrim = confirmDialog(actions({ confirming: "restart" }), fakeCtx());
  assert.ok(scrim);
  assert.match(scrim.textContent, /Restart the dashboard\?/);
  assert.equal(withClass(scrim, "admin-dbtn")[1].textContent, "Restart");
});
