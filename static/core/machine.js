// Layout-agnostic fetch/poll/refresh/rollover/clock engine: it owns when to
// render, the layout owns what renders. The core graph is side-effect-free on
// import (DOM access happens only after init()), so node:test can import it
// without a DOM.

import { localDayKey, dayRolledOver } from "./time.js";

/** @typedef {import("./contract.js").DashboardDoc} DashboardDoc */
/** @typedef {import("./contract.js").Layout} Layout */
/** @typedef {import("./contract.js").IconPack} IconPack */

const DATA_URL = "/api/data";

// Matches the backend's fetch cadence.
const POLL_INTERVAL_MS = 15 * 60 * 1000;

// Short cadence while unsettled, so the cold-boot 503 window (cache not warm)
// and the pre-NTP-sync window clear in seconds rather than up to 15 min.
const RETRY_INTERVAL_MS = 30 * 1000;

/**
 * Nothing runs until `init()`. `ctx` (the icon pack) is forwarded verbatim to
 * the layout's mount; the core never inspects it.
 * @param {Layout} layout
 * @param {{ icon: IconPack }} ctx
 * @returns {{ init: () => void }}
 */
export function createApp(layout, ctx) {
  // Before the first success a failed load shows placeholders in every region;
  // after it, the last-good render stays and only the freshness dots go stale.
  let hasRendered = false;

  // Only an explicit false (Pi not NTP-synced yet, ~1 min after boot) counts as
  // unsynced; undefined (dev host, older cache) is treated as fine.
  /** @type {boolean | undefined} */
  let lastClockSynced;

  // Flips at midnight to reload, so the agenda rolls without waiting for a poll.
  /** @type {string | null} */
  let currentDay = null;

  function renderClockNow() {
    layout.renderClock(new Date(), lastClockSynced !== false);
  }

  // POST /refresh is serialized server-side against the background loop, so it
  // can't race a scheduled tick into a double-fetch.
  /** @returns {Promise<void>} */
  async function refresh() {
    const res = await fetch("/refresh", { method: "POST", cache: "no-store" });
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    await load();
  }

  // Returns true on success; on failure degrades visibly, never a blank panel.
  /** @returns {Promise<boolean>} */
  async function load() {
    try {
      const res = await fetch(DATA_URL, { cache: "no-store" });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      /** @type {DashboardDoc} */
      const data = await res.json();
      layout.renderCurrent(data.weather);
      layout.renderForecast(data.weather.forecast);
      layout.renderAgenda(data.calendar.events, data.calendar.ok, data.clock_synced);
      layout.renderStatus(data, { refresh });
      lastClockSynced = data.clock_synced;
      renderClockNow();
      hasRendered = true;
      return true;
    } catch (err) {
      console.error("dashboard load failed:", err);
      layout.renderStatus(null, { stale: true, refresh });
      if (!hasRendered) layout.renderUnavailable();
      return false;
    }
  }

  // A setTimeout chain, not setInterval, so a slow fetch can't stack polls.
  async function tick() {
    const ok = await load();
    const settled = ok && lastClockSynced !== false;
    setTimeout(tick, settled ? POLL_INTERVAL_MS : RETRY_INTERVAL_MS);
  }

  function init() {
    // Fail loud (caught by app.js) rather than mount(null).
    const root = document.getElementById("app");
    if (!root) throw new Error('mount root #app not found in the document');
    layout.mount(root, ctx);
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
