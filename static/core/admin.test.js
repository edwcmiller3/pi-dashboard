// Unit tests for core/admin.js - the layout-agnostic admin controller. Run with
// `node --test` from static/.
//
// The controller only toggles the overlay root and drives an injected skin, so a
// plain-object root and a recording fake skin are enough - no DOM stub.

import test from "node:test";
import assert from "node:assert/strict";

import { createAdmin } from "./admin.js";

/** A fake AdminSkin recording every mount; exposes the ctx it was handed. */
/** Offline, timer-free edges for the open/close tests (no real fetch/interval). */
const QUIET = {
  fetch: async () => {
    throw new Error("offline");
  },
  every: () => () => {},
};

function fakeSkin() {
  const skin = {
    /** @type {{ root: unknown, ctx: any }[]} */
    mounts: [],
    /** @param {unknown} root @param {any} ctx */
    mount(root, ctx) {
      skin.mounts.push({ root, ctx });
    },
    renderConfig() {},
    renderStats() {},
    renderActions() {},
    renderTransition() {},
  };
  return skin;
}

test("admin: open reveals the overlay root; close hides it", () => {
  const root = { hidden: true };
  const admin = createAdmin(fakeSkin(), { root, io: QUIET });
  admin.open();
  assert.equal(root.hidden, false);
  admin.close();
  assert.equal(root.hidden, true);
});

test("admin: the skin mounts into the overlay root once, on first open", () => {
  const root = { hidden: true };
  const skin = fakeSkin();
  const admin = createAdmin(skin, { root, io: QUIET });
  assert.equal(skin.mounts.length, 0, "constructing must not touch the DOM");
  admin.open();
  admin.close();
  admin.open();
  assert.equal(skin.mounts.length, 1, "re-open reuses the mounted shell");
  assert.equal(skin.mounts[0].root, root);
});

test("admin: the skin's back hook returns to the dashboard route", (t) => {
  const prev = globalThis.location;
  t.after(() => {
    globalThis.location = prev;
  });
  globalThis.location = /** @type {any} */ ({ hash: "#admin" });
  const skin = fakeSkin();
  createAdmin(skin, { root: { hidden: true }, io: QUIET }).open();
  skin.mounts[0].ctx.back();
  assert.equal(globalThis.location.hash, "");
});

test("admin: close before any open is harmless", () => {
  const root = { hidden: true };
  const skin = fakeSkin();
  createAdmin(skin, { root, io: QUIET }).close();
  assert.equal(root.hidden, true);
  assert.equal(skin.mounts.length, 0);
});

// ── config panel + apply state machine ───────────────────────────────────────

const CONFIG = {
  layout: { current: "classic", options: ["classic", "hud", "swiss-mono"] },
  theme: { current: "", options: ["", "nord"] },
  icon_pack: { current: "weather-icons", options: ["weather-icons", "meteocons-flat"] },
};
const OLD_BOOT = "boot-old";
const NEW_BOOT = "boot-new";

const GET_CONFIG = "GET /api/admin/config";
const POST_CONFIG = "POST /api/admin/config";
const HEALTHZ = "GET /healthz";
const GET_STATS = "GET /api/admin/stats";

const STATS = {
  cpu_percent: 22,
  memory: { used: 1, total: 4 },
  disk: { used: 4, total: 29 },
  uptime_s: 31_560,
  host: "pi",
  temp_c: null,
  throttle: null,
  network: null,
};

/** @typedef {{ status: number, body?: unknown } | Error} Reply */

/**
 * A scripted fetch keyed by "METHOD url": each call consumes the next scripted
 * reply (the last one repeats); an Error rejects, like a refused connection.
 * @param {Record<string, Reply[]>} script
 */
function fakeFetch(script) {
  /** @type {{ url: string, init: any }[]} */
  const calls = [];
  /** @param {string} url @param {any} [init] */
  async function f(url, init = {}) {
    calls.push({ url, init });
    const queue = script[`${init.method ?? "GET"} ${url}`];
    if (!queue) throw new Error(`unscripted fetch ${init.method ?? "GET"} ${url}`);
    const next = queue.length > 1 ? queue.shift() : queue[0];
    if (next instanceof Error) throw next;
    return { ok: next.status < 400, status: next.status, json: async () => next.body };
  }
  return Object.assign(f, { calls });
}

/** Drain the microtask chain behind a fire-and-forget load. */
const flush = () => new Promise((r) => setTimeout(r, 0));

/** A skin recording every config view and transition it was asked to paint. */
function recordingSkin() {
  const base = fakeSkin();
  /** @type {any[]} */
  const views = [];
  /** @type {[string | null, string | undefined][]} */
  const transitions = [];
  /** @type {any[]} */
  const stats = [];
  return {
    ...base,
    views,
    transitions,
    stats,
    /** @param {any} s */
    renderStats(s) {
      stats.push(s);
    },
    /** @param {any} v */
    renderConfig(v) {
      views.push(v);
    },
    /** @param {string | null} s @param {string} [m] */
    renderTransition(s, m) {
      transitions.push([s, m]);
    },
    get last() {
      return views[views.length - 1];
    },
    get ctx() {
      return base.mounts[0].ctx;
    },
  };
}

/**
 * An opened controller over a scripted fetch and a fake clock: `sleep` advances
 * the clock instantly, so the healthz poll and its timeout run without waiting.
 * @param {Record<string, Reply[]>} [script]
 */
async function opened(script = {}) {
  const fetch = fakeFetch({
    [GET_CONFIG]: [{ status: 200, body: CONFIG }],
    [GET_STATS]: [{ status: 200, body: STATS }],
    ...script,
  });
  let t = 0;
  let reloads = 0;
  /** @type {{ ms: number, fn: () => void, cancelled: boolean }[]} */
  const timers = [];
  const io = {
    fetch,
    reload: () => void reloads++,
    /** @param {number} ms */
    sleep: async (ms) => void (t += ms),
    now: () => t,
    /** @param {number} ms @param {() => void} fn */
    every: (ms, fn) => {
      const timer = { ms, fn, cancelled: false };
      timers.push(timer);
      return () => void (timer.cancelled = true);
    },
  };
  const skin = recordingSkin();
  const admin = createAdmin(skin, { root: { hidden: true }, io });
  admin.open();
  await flush();
  return { admin, skin, fetch, timers, reloads: () => reloads, elapsed: () => t };
}

/** @param {{ calls: { url: string, init: any }[] }} fetch */
const posts = (fetch) => fetch.calls.filter((c) => c.init.method === "POST");

const RESTARTED = { status: 200, body: { restarted: true, boot: OLD_BOOT } };

test("config: open loads the knobs uncached and renders them with nothing staged", async () => {
  const { skin, fetch } = await opened();
  assert.deepEqual(fetch.calls[0], { url: "/api/admin/config", init: { cache: "no-store" } });
  assert.deepEqual(skin.last.config, CONFIG);
  assert.deepEqual(skin.last.staged, {});
  assert.equal(skin.last.pending, 0);
  assert.equal(skin.last.busy, false);
});

test("config: a failed load renders the panel unavailable, not a throw", async () => {
  const { skin } = await opened({ [GET_CONFIG]: [new TypeError("refused")] });
  assert.equal(skin.last.config, null);
  assert.equal(skin.last.notice.kind, "error");
});

test("config: a non-200 load is unavailable too", async () => {
  const { skin } = await opened({ [GET_CONFIG]: [{ status: 500, body: {} }] });
  assert.equal(skin.last.config, null);
  assert.equal(skin.last.notice.kind, "error");
});

test("config: staging counts a change; re-selecting the live value un-stages it", async () => {
  const { skin } = await opened();
  skin.ctx.stage("theme", "nord");
  skin.ctx.stage("layout", "hud");
  assert.deepEqual(skin.last.staged, { theme: "nord", layout: "hud" });
  assert.equal(skin.last.pending, 2);
  skin.ctx.stage("theme", "");
  assert.deepEqual(skin.last.staged, { layout: "hud" });
  assert.equal(skin.last.pending, 1);
});

test("config: re-opening discards an un-applied stage", async () => {
  const { admin, skin } = await opened();
  skin.ctx.stage("layout", "hud");
  admin.close();
  admin.open();
  await flush();
  assert.deepEqual(skin.last.staged, {});
});

test("apply: nothing staged sends nothing", async () => {
  const { skin, fetch } = await opened();
  await skin.ctx.apply();
  assert.equal(posts(fetch).length, 0);
});

test("apply: posts the staged JSON, then reloads only once a NEW process is healthy", async () => {
  const { skin, fetch, reloads } = await opened({
    [POST_CONFIG]: [RESTARTED],
    [HEALTHZ]: [
      { status: 200, body: { status: "ok", boot: OLD_BOOT } }, // not yet stopped
      new TypeError("connection refused"), // the down window
      { status: 503, body: {} }, // starting up
      { status: 200, body: { status: "ok", boot: NEW_BOOT } },
    ],
  });
  skin.ctx.stage("layout", "hud");
  await skin.ctx.apply();

  const [post] = posts(fetch);
  assert.equal(post.init.headers["Content-Type"], "application/json");
  assert.deepEqual(JSON.parse(post.init.body), { layout: "hud" });
  assert.deepEqual(skin.transitions, [["applying", undefined]]);
  const polls = fetch.calls.filter((c) => c.url === "/healthz");
  assert.equal(polls.length, 4, "kept polling past the old process and the down window");
  assert.ok(polls.every((c) => c.init.cache === "no-store"));
  assert.equal(reloads(), 1);
});

test("apply: a backend that never comes back shows the error state, never reloads", async () => {
  const { skin, reloads, elapsed } = await opened({
    [POST_CONFIG]: [RESTARTED],
    [HEALTHZ]: [new TypeError("connection refused")],
  });
  skin.ctx.stage("theme", "nord");
  await skin.ctx.apply();
  assert.equal(reloads(), 0);
  const [state, message] = skin.transitions[skin.transitions.length - 1];
  assert.equal(state, "error");
  assert.match(String(message), /did not come back healthy/);
  assert.ok(elapsed() >= 30_000 && elapsed() < 32_000, "gives up after ~30s");
});

test("apply: dismissing the error returns to a fresh, idle panel", async () => {
  const { skin } = await opened({
    [POST_CONFIG]: [RESTARTED],
    [HEALTHZ]: [new TypeError("connection refused")],
  });
  skin.ctx.stage("theme", "nord");
  await skin.ctx.apply();
  skin.ctx.dismiss();
  await flush();
  assert.deepEqual(skin.transitions[skin.transitions.length - 1], [null, undefined]);
  assert.equal(skin.last.busy, false);
  assert.deepEqual(skin.last.staged, {});
  assert.deepEqual(skin.last.config, CONFIG, "re-read what is actually live");
});

test("apply: a no-op reply clears the stage and says so, with no restart", async () => {
  const { skin, fetch, reloads } = await opened({
    [POST_CONFIG]: [{ status: 200, body: { restarted: false } }],
  });
  skin.ctx.stage("layout", "hud");
  await skin.ctx.apply();
  assert.deepEqual(skin.last.staged, {});
  assert.equal(skin.last.busy, false);
  assert.equal(skin.last.notice.kind, "info");
  assert.equal(skin.transitions.length, 0);
  assert.equal(fetch.calls.filter((c) => c.url === "/healthz").length, 0);
  assert.equal(reloads(), 0);
});

test("apply: a rejected apply surfaces the server's reason and keeps the stage", async () => {
  const { skin, reloads } = await opened({
    [POST_CONFIG]: [{ status: 400, body: { detail: "unknown layout: 'x'" } }],
  });
  skin.ctx.stage("layout", "hud");
  await skin.ctx.apply();
  assert.deepEqual(skin.last.notice, { kind: "error", text: "unknown layout: 'x'" });
  assert.deepEqual(skin.last.staged, { layout: "hud" }, "nothing changed; retry is one tap");
  assert.equal(skin.last.busy, false);
  assert.equal(skin.transitions.length, 0);
  assert.equal(reloads(), 0);
});

test("apply: an unreachable backend is an error notice, not a throw", async () => {
  const { skin } = await opened({ [POST_CONFIG]: [new TypeError("refused")] });
  skin.ctx.stage("layout", "hud");
  await skin.ctx.apply();
  assert.equal(skin.last.notice.kind, "error");
  assert.equal(skin.last.busy, false);
});

test("apply: the panel is inert while an apply is in flight", async () => {
  /** @type {(v: any) => void} */
  let release = () => {};
  const { skin, fetch } = await opened();
  // Hold the POST open to observe the in-flight state.
  const inner = fetch;
  /** @param {string} url @param {any} [init] */
  const held = (url, init = {}) =>
    init.method === "POST"
      ? new Promise((r) => {
          release = r;
        })
      : inner(url, init);
  skin.mounts.length = 0;
  const admin = createAdmin(skin, { root: { hidden: true }, io: { fetch: held, every: QUIET.every } });
  admin.open();
  await flush();
  skin.ctx.stage("layout", "hud");
  const pending = skin.ctx.apply();
  assert.equal(skin.last.busy, true);
  skin.ctx.stage("theme", "nord");
  void skin.ctx.apply();
  assert.deepEqual(skin.last.staged, { layout: "hud" }, "stage ignored while busy");
  release({ ok: true, status: 200, json: async () => ({ restarted: false }) });
  await pending;
  assert.equal(skin.last.busy, false);
});

// ── stats auto-poll ──────────────────────────────────────────────────────────

/** @param {{ calls: { url: string }[] }} fetch */
const statsCalls = (fetch) => fetch.calls.filter((c) => c.url === "/api/admin/stats");

test("stats: open fetches uncached right away and renders, then polls every 5s", async () => {
  const { skin, fetch, timers } = await opened();
  assert.deepEqual(statsCalls(fetch)[0], { url: "/api/admin/stats", init: { cache: "no-store" } });
  assert.deepEqual(skin.stats, [STATS]);
  assert.equal(timers.length, 1);
  assert.equal(timers[0].ms, 5000);
  timers[0].fn();
  await flush();
  assert.equal(statsCalls(fetch).length, 2);
  assert.equal(skin.stats.length, 2);
});

test("stats: close stops the poll; re-open restarts exactly one", async () => {
  const { admin, timers } = await opened();
  admin.close();
  assert.equal(timers[0].cancelled, true);
  admin.open();
  await flush();
  assert.equal(timers.filter((t) => !t.cancelled).length, 1);
});

test("stats: a repeated open without close never stacks a second poll", async () => {
  const { admin, timers } = await opened();
  admin.open();
  await flush();
  assert.equal(timers.filter((t) => !t.cancelled).length, 1);
});

test("stats: a failed poll renders the panel unavailable, not a throw", async () => {
  const { skin, timers } = await opened({ [GET_STATS]: [{ status: 200, body: STATS }, new TypeError("refused")] });
  timers[0].fn();
  await flush();
  assert.deepEqual(skin.stats, [STATS, null]);
});

test("stats: a non-200 poll is unavailable too", async () => {
  const { skin } = await opened({ [GET_STATS]: [{ status: 500, body: {} }] });
  assert.deepEqual(skin.stats, [null]);
});

test("stats: a tick while the last poll is still in flight is skipped", async () => {
  /** @type {(v: any) => void} */
  let release = () => {};
  let held = 0;
  /** @type {(() => void)[]} */
  const ticks = [];
  /** @param {string} url */
  const fetch = (url) => {
    if (url !== "/api/admin/stats") return Promise.reject(new Error("offline"));
    held++;
    return new Promise((r) => {
      release = r;
    });
  };
  const admin = createAdmin(recordingSkin(), {
    root: { hidden: true },
    io: { fetch, every: (_ms, fn) => (ticks.push(fn), () => {}) },
  });
  admin.open();
  ticks[0]();
  ticks[0]();
  assert.equal(held, 1, "ticks during the held call send nothing");
  release({ ok: true, status: 200, json: async () => STATS });
  await flush();
  ticks[0]();
  assert.equal(held, 2, "the next tick after it settles polls again");
});
