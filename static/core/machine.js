// Core state machine - the layout-agnostic fetch/poll/refresh/rollover/clock
// engine. It reads the live JSON API (/api/data), which the backend refresh
// loop keeps warm, and drives a layout's render hooks; it owns WHEN to render,
// the layout owns WHAT renders. Importing this module runs no side effects - the
// browser-only bootstrap lives in the entry module (static/app.js), guarded by
// `typeof document`, so `node --test` can import the pure core without a DOM.

import { localDayKey, dayRolledOver } from "./time.js";

/** @typedef {import("./contract.js").DashboardDoc} DashboardDoc */
/** @typedef {import("./contract.js").Layout} Layout */

const DATA_URL = "/api/data";

// How often the page re-fetches the API - a fixed poll matching the backend's
// fetch cadence.
const POLL_INTERVAL_MS = 15 * 60 * 1000;

// After a FAILED load, retry soon rather than waiting the full poll - so the
// cold-boot 503 window (cache not yet warm) and transient blips clear in
// seconds, not up to 15 minutes.
const RETRY_INTERVAL_MS = 30 * 1000;

/**
 * Build the dashboard state machine bound to one layout. Returns the bootstrap
 * handle; nothing runs until `init()` is called (from the browser entry point).
 * @param {Layout} layout
 * @returns {{ init: () => void }}
 */
export function createApp(layout) {
  // True once at least one fetch has painted real data. Drives how failures
  // degrade: BEFORE the first success (the cold-boot 503 window) we show honest
  // "unavailable" placeholders in EVERY data region; AFTER it, a failed poll
  // leaves the last-good render on screen and only flips the freshness dots
  // stale - so weather and the agenda degrade alike, never one wiped while the
  // other stays.
  let hasRendered = false;

  // Last clock_synced value the API reported (true/false/undefined). When the
  // backend explicitly says false - the Pi clock isn't NTP-synced yet, e.g. the
  // ~1-min post-boot window before timesyncd lands - `tick` polls at the short
  // retry cadence instead of the 15-min one, so the "clock not synced" warning
  // clears promptly after sync rather than at the next slow poll. undefined/true
  // (dev host, older cache) is treated as fine.
  /** @type {boolean | undefined} */
  let lastClockSynced;

  // The local day we last rendered for; flips at midnight to trigger a reload so
  // the agenda rolls (today→tomorrow, new in-window holidays/events) without
  // waiting for the next poll. The clock itself already ticks live each second.
  /** @type {string | null} */
  let currentDay = null;

  // Live wall-clock tick + clock-sync honesty in one hook. `synced` is a plain
  // boolean: true when the Pi clock is trustworthy (or its state is unknown -
  // dev host / older cache), false only when the backend explicitly reports
  // clock_synced === false, which is when the layout surfaces its warning.
  function renderClockNow() {
    layout.renderClock(new Date(), lastClockSynced !== false);
  }

  // Force an immediate backend refetch of every source, then reload the contract
  // to repaint. POST /refresh is serialized server-side (asyncio.Lock) against
  // the background loop, so this can't race a scheduled tick into a
  // double-fetch. The layout wires its refresh control to this (via the
  // renderStatus opts) and owns the in-flight/error UI.
  /** @returns {Promise<void>} */
  async function refresh() {
    const res = await fetch("/refresh", { method: "POST", cache: "no-store" });
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    await load(); // repaint with the freshly-refreshed doc
  }

  // Fetch the contract and repaint every data region. Returns true on success.
  // On any failure (including the 503 the API returns before its first refresh
  // tick) degrade visibly - stale dots, dashed "Updated", honest placeholders on
  // cold boot, last-good kept otherwise - never a blank panel.
  /** @returns {Promise<boolean>} */
  async function load() {
    try {
      const res = await fetch(DATA_URL, { cache: "no-store" });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      // The untyped JSON boundary - assert the contract so the render pipeline
      // downstream is checked against DashboardDoc (mirrors the backend typing).
      /** @type {DashboardDoc} */
      const data = await res.json();
      layout.renderCurrent(data.weather);
      layout.renderForecast(data.weather.forecast);
      layout.renderAgenda(data.calendar.events, data.calendar.ok, data.clock_synced);
      layout.renderStatus(data, { refresh });
      lastClockSynced = data.clock_synced;
      renderClockNow(); // reflect the fresh clock-sync state in the warning
      hasRendered = true;
      return true;
    } catch (err) {
      console.error("dashboard load failed:", err);
      layout.renderStatus(null, { stale: true, refresh });
      // No good data has ever painted → honest placeholders. After a prior
      // success → leave the last-good render untouched; only the dots go stale.
      if (!hasRendered) layout.renderUnavailable();
      return false;
    }
  }

  // Self-scheduling poll: on success, next fetch in POLL_INTERVAL_MS; on failure,
  // retry in the shorter RETRY_INTERVAL_MS. A single timer chain (not setInterval)
  // so a slow fetch can't stack overlapping polls.
  async function tick() {
    const ok = await load();
    // Use the slow cadence only once we're settled: a successful load AND the Pi
    // clock is synced. A failed load or an explicit clock_synced===false keeps us
    // on the short retry cadence so both the cold-boot 503 window and the
    // pre-NTP-sync window clear in ~30s steps, not up to 15 min.
    const settled = ok && lastClockSynced !== false;
    setTimeout(tick, settled ? POLL_INTERVAL_MS : RETRY_INTERVAL_MS);
  }

  function init() {
    // Guard the one required mount point rather than casting a possibly-null
    // lookup to HTMLElement: a missing #app is a broken index.html, so fail loud
    // (caught by app.js's try/catch net) instead of calling mount(null).
    const root = document.getElementById("app");
    if (!root) throw new Error('mount root #app not found in the document');
    layout.mount(root);
    renderClockNow();
    currentDay = localDayKey();
    setInterval(() => {
      renderClockNow();
      const today = localDayKey();
      if (dayRolledOver(currentDay, today)) load();
      currentDay = today;
    }, 1000);
    tick();
  }

  return { init };
}
