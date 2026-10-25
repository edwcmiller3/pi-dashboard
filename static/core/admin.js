// Core admin controller - the layout-agnostic half of the admin screen.
//
// Mirrors the core/layout split: this module owns WHEN/behavior, the injected
// AdminSkin (layouts/<slug>/admin.js) owns WHAT renders and all its DOM/CSS.
// Admin is an overlay over the still-running dashboard (machine.js has no
// teardown), so open/close only reveal/hide #admin-root; the clock and poll
// underneath never stop.
//
// Side-effect-free on import (the core graph's invariant, see core/machine.js).

import { go } from "./router.js";

/** @typedef {import("./contract.js").AdminAction} AdminAction */
/** @typedef {import("./contract.js").AdminSkin} AdminSkin */
/** @typedef {import("./contract.js").AdminConfig} AdminConfig */
/** @typedef {import("./contract.js").AdminStats} AdminStats */
/** @typedef {import("./contract.js").ConfigKey} ConfigKey */
/** @typedef {import("./contract.js").ConfigView} ConfigView */

/**
 * The controller's impure edges, injectable so node:test can drive the apply
 * state machine without a network, a page reload, or real time.
 * @typedef {object} AdminIO
 * @property {(url: string, init?: RequestInit) => Promise<Response>} fetch
 * @property {() => void} reload
 * @property {(ms: number) => Promise<void>} sleep
 * @property {() => number} now ms clock
 * @property {(ms: number, fn: () => void) => () => void} every repeating timer;
 *   returns its cancel
 */

/** @typedef {{ restarted: boolean, boot?: string }} ApplyReply POST /api/admin/config */
/** @typedef {{ ok: boolean, status: number, body: any }} PostReply */

const HEALTH_POLL_MS = 1000;
const HEALTH_TIMEOUT_MS = 30_000;
// Runs for as long as admin stays open (no idle auto-return), so it is kept slow
// for the Pi's thermal budget; each poll also costs a ~0.1s CPU sample server-side.
const STATS_POLL_MS = 5000;

/** @type {AdminIO} */
const BROWSER_IO = {
  fetch: (url, init) => globalThis.fetch(url, init),
  reload: () => globalThis.location.reload(),
  sleep: (ms) => new Promise((resolve) => setTimeout(resolve, ms)),
  now: () => Date.now(),
  every: (ms, fn) => {
    const id = setInterval(fn, ms);
    return () => clearInterval(id);
  },
};

/**
 * @param {AdminSkin} skin the LAYOUT-selected admin skin
 * @param {{ root: HTMLElement, io?: Partial<AdminIO> }} ctx `root` is the overlay
 *   container (#admin-root)
 * @returns {{ open: () => void, close: () => void }}
 */
export function createAdmin(skin, { root, io = {} }) {
  const { fetch, reload, sleep, now, every } = { ...BROWSER_IO, ...io };
  let mounted = false;

  /** @type {AdminConfig | null} */
  let config = null;
  /** @type {Partial<Record<ConfigKey, string>>} */
  let staged = {};
  let busy = false;
  /** @type {ConfigView["notice"]} */
  let notice = null;
  /** @type {(() => void) | null} */
  let stopStats = null;
  let statsInFlight = false;
  /** @type {boolean | null} */
  let rebootOk = null;
  /** @type {AdminAction | null} */
  let confirming = null;
  let acting = false;
  /** @type {string | null} */
  let actionError = null;

  function render() {
    skin.renderConfig({ config, staged: { ...staged }, pending: Object.keys(staged).length, busy, notice });
  }

  function renderActions() {
    skin.renderActions({ reboot: rebootOk, confirming, busy: acting, error: actionError });
  }

  /**
   * POST a JSON body (one is required server-side, which blocks cross-origin
   * simple POSTs). Rejects only when the service is unreachable.
   * @param {string} url @param {object} payload @returns {Promise<PostReply>}
   */
  async function post(url, payload) {
    const res = await fetch(url, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
      cache: "no-store",
    });
    return { ok: res.ok, status: res.status, body: await res.json().catch(() => ({})) };
  }

  async function loadConfig() {
    try {
      const res = await fetch("/api/admin/config", { cache: "no-store" });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      config = /** @type {AdminConfig} */ (await res.json());
    } catch (err) {
      console.error("admin config failed to load:", err);
      config = null;
      notice = { kind: "error", text: "Settings unavailable" };
    }
    render();
  }

  async function loadRebootAvailable() {
    try {
      const res = await fetch("/api/admin/reboot", { cache: "no-store" });
      rebootOk = res.ok && (await res.json()).available === true;
    } catch {
      rebootOk = false;
    }
    renderActions();
  }

  async function pollStats() {
    // A slow probe must not stack requests behind it.
    if (statsInFlight) return;
    statsInFlight = true;
    try {
      const res = await fetch("/api/admin/stats", { cache: "no-store" });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      skin.renderStats(/** @type {AdminStats} */ (await res.json()));
    } catch {
      // Includes the restart window under an apply; the next tick recovers.
      skin.renderStats(null);
    } finally {
      statsInFlight = false;
    }
  }

  /** @param {ConfigKey} key @param {string} value */
  function stage(key, value) {
    if (busy || acting || !config) return;
    const { [key]: _, ...rest } = staged;
    staged = value === config[key].current ? rest : { ...rest, [key]: value };
    notice = null;
    render();
  }

  /** @param {string} text */
  function fail(text) {
    busy = false;
    notice = { kind: "error", text };
    render();
  }

  // Wait for a process OTHER than the one that accepted the apply: the restart
  // fires ~1s after the reply, so a healthy answer before then is the old one.
  /** @param {string | undefined} prevBoot @returns {Promise<boolean>} */
  async function restarted(prevBoot) {
    const deadline = now() + HEALTH_TIMEOUT_MS;
    while (now() < deadline) {
      await sleep(HEALTH_POLL_MS);
      try {
        const res = await fetch("/healthz", { cache: "no-store" });
        if (res.ok && (await res.json()).boot !== prevBoot) return true;
      } catch {
        // Connection refused is expected while the service is down.
      }
    }
    return false;
  }

  async function apply() {
    if (busy || acting || Object.keys(staged).length === 0) return;
    busy = true;
    notice = null;
    render();

    /** @type {ApplyReply} */
    let reply;
    try {
      const { ok, status, body } = await post("/api/admin/config", staged);
      if (!ok) return fail(body.detail ?? `Apply failed (HTTP ${status})`);
      reply = body;
    } catch {
      return fail("Couldn't reach the dashboard service");
    }

    if (!reply.restarted) {
      busy = false;
      staged = {};
      notice = { kind: "info", text: "No changes to apply" };
      return render();
    }
    skin.renderTransition("applying");
    // The router clears #admin on boot, so the reload lands on the dashboard.
    if (await restarted(reply.boot)) reload();
    else skin.renderTransition("error", "The dashboard did not come back healthy.");
  }

  // The confirm gate: request() only opens the dialog; confirm() fires. A stray
  // tap can at worst open a dialog, never drop the wall.
  /** @param {AdminAction} action */
  function request(action) {
    if (busy || acting || (action === "reboot" && !rebootOk)) return;
    confirming = action;
    actionError = null;
    renderActions();
  }

  function cancel() {
    confirming = null;
    renderActions();
  }

  /** @param {string} text */
  function actionFailed(text) {
    acting = false;
    actionError = text;
    renderActions();
  }

  async function confirm() {
    const action = confirming;
    if (!action || busy || acting) return;
    confirming = null;
    acting = true;
    actionError = null;
    renderActions();

    /** @type {PostReply} */
    let reply;
    try {
      reply = await post(`/api/admin/${action}`, {});
    } catch {
      return actionFailed("Couldn't reach the dashboard service");
    }
    if (!reply.ok) {
      // 503 = polkit refused: the availability check was stale.
      if (action === "reboot" && reply.status === 503) rebootOk = false;
      const name = action === "reboot" ? "Reboot" : "Restart";
      return actionFailed(reply.body.detail ?? `${name} failed (HTTP ${reply.status})`);
    }
    // Terminal: the screen goes dark, and boot brings the dashboard back.
    if (action === "reboot") return skin.renderTransition("rebooting");
    skin.renderTransition("applying");
    if (await restarted(reply.body.boot)) reload();
    else skin.renderTransition("error", "The dashboard did not come back healthy.");
  }

  function dismiss() {
    skin.renderTransition(null);
    busy = false;
    staged = {};
    notice = null;
    acting = false;
    actionError = null;
    confirming = null;
    renderActions();
    void loadConfig();
  }

  function open() {
    // Mount lazily and once: the shell persists across open/close.
    if (!mounted) {
      skin.mount(root, { back: () => go(""), stage, apply, dismiss, request, confirm, cancel });
      mounted = true;
    }
    root.hidden = false;
    // A fresh read each open: a stale stage or confirm must never survive a revisit.
    if (!busy && !acting) {
      staged = {};
      notice = null;
      confirming = null;
      actionError = null;
      render();
      renderActions();
      void loadConfig();
      void loadRebootAvailable();
    }
    stopStats?.();
    void pollStats();
    stopStats = every(STATS_POLL_MS, () => void pollStats());
  }

  function close() {
    root.hidden = true;
    stopStats?.();
    stopStats = null;
  }

  return { open, close };
}
