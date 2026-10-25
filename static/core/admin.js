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

/** @typedef {import("./contract.js").AdminSkin} AdminSkin */
/** @typedef {import("./contract.js").AdminConfig} AdminConfig */
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
 */

/** @typedef {{ restarted: boolean, boot?: string }} ApplyReply POST /api/admin/config */

const HEALTH_POLL_MS = 1000;
const HEALTH_TIMEOUT_MS = 30_000;

/** @type {AdminIO} */
const BROWSER_IO = {
  fetch: (url, init) => globalThis.fetch(url, init),
  reload: () => globalThis.location.reload(),
  sleep: (ms) => new Promise((resolve) => setTimeout(resolve, ms)),
  now: () => Date.now(),
};

/**
 * @param {AdminSkin} skin the LAYOUT-selected admin skin
 * @param {{ root: HTMLElement, io?: Partial<AdminIO> }} ctx `root` is the overlay
 *   container (#admin-root)
 * @returns {{ open: () => void, close: () => void }}
 */
export function createAdmin(skin, { root, io = {} }) {
  const { fetch, reload, sleep, now } = { ...BROWSER_IO, ...io };
  let mounted = false;

  /** @type {AdminConfig | null} */
  let config = null;
  /** @type {Partial<Record<ConfigKey, string>>} */
  let staged = {};
  let busy = false;
  /** @type {ConfigView["notice"]} */
  let notice = null;

  function render() {
    skin.renderConfig({ config, staged: { ...staged }, pending: Object.keys(staged).length, busy, notice });
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

  /** @param {ConfigKey} key @param {string} value */
  function stage(key, value) {
    if (busy || !config) return;
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
    if (busy || Object.keys(staged).length === 0) return;
    busy = true;
    notice = null;
    render();

    /** @type {ApplyReply} */
    let reply;
    try {
      const res = await fetch("/api/admin/config", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(staged),
        cache: "no-store",
      });
      const body = await res.json().catch(() => ({}));
      if (!res.ok) return fail(body.detail ?? `Apply failed (HTTP ${res.status})`);
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

  function dismiss() {
    skin.renderTransition(null);
    busy = false;
    staged = {};
    notice = null;
    void loadConfig();
  }

  function open() {
    // Mount lazily and once: the shell persists across open/close.
    if (!mounted) {
      skin.mount(root, { back: () => go(""), stage, apply, dismiss });
      mounted = true;
    }
    root.hidden = false;
    // A fresh read each open: a stale stage must never survive a revisit.
    if (!busy) {
      staged = {};
      notice = null;
      render();
      void loadConfig();
    }
  }

  function close() {
    root.hidden = true;
  }

  return { open, close };
}
