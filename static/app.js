// Pi Dashboard entry point - the thin bootstrap wiring the layout-agnostic
// core state machine to a concrete layout, then booting it in the browser.
//
// The layout comes from the server's /layout.js route (a generated one-line
// re-export of the LAYOUT-selected module - classic by default), so selection
// is server-side config, mirroring the theme mechanism. The icon pack comes from
// the parallel /pack.js route (the ICON_PACK-selected module - weather-icons by
// default) and is injected into the layout via createApp's ctx, so a layout
// never names a pack. The stable entry name (app.js) keeps index.html's <script>
// and the static-freshness tests unchanged.

import { createApp } from "./core/machine.js";
import { onRoute, go } from "./core/router.js";
import { layout } from "/layout.js";
import { iconPack } from "/pack.js";

/** @typedef {{ open: () => void, close: () => void }} AdminController */

// Resolve once the stylesheet has loaded (or failed - an unstyled admin still
// beats one that never opens), so the overlay is never revealed unstyled.
/** @param {string} href @returns {Promise<void>} */
function loadStylesheet(href) {
  return new Promise((resolve) => {
    const link = document.createElement("link");
    link.rel = "stylesheet";
    link.href = href;
    link.onload = link.onerror = () => resolve();
    document.head.append(link);
  });
}

// Admin is rarely opened, so its skin (/admin.js + /admin.css, LAYOUT-selected
// server-side like /layout.js) and controller stay out of the boot graph and
// load on first open. Cached; a failed load is dropped so the next tap retries.
/** @type {Promise<AdminController> | null} */
let adminLoad = null;

/** @returns {Promise<AdminController>} */
function loadAdmin() {
  adminLoad ??= Promise.all([import("/admin.js"), import("./core/admin.js"), loadStylesheet("/admin.css")])
    .then(([{ admin }, { createAdmin }]) => {
      const root = document.getElementById("admin-root");
      if (!root) throw new Error("overlay root #admin-root not found in the document");
      return createAdmin(admin, { root });
    })
    .catch((err) => {
      adminLoad = null;
      throw err;
    });
  return adminLoad;
}

const adminRoute = {
  async open() {
    try {
      const admin = await loadAdmin();
      // The back arrow may have been tapped while the bundle loaded.
      if (location.hash === "#admin") admin.open();
    } catch (err) {
      // Fail-soft: stay on the dashboard, and clear #admin so the cog works again.
      console.error("admin failed to open:", err);
      go("");
    }
  },
  close() {
    adminLoad?.then((admin) => admin.close(), () => {});
  },
};

// Browser-only bootstrap. Guarded so importing the module graph under node:test
// (the pure-function unit tests) runs no DOM/init side effects. Fail-soft: a
// layout throwing on mount must not leave an unhandled error - the plan's
// blank-kiosk mitigation. Classic never throws in practice; this net lets a
// later, riskier layout degrade instead of killing the wall display.
if (typeof document !== "undefined") {
  try {
    createApp(layout, { icon: iconPack }).init();
  } catch (err) {
    console.error("layout failed to mount:", err);
  }
  onRoute({ admin: adminRoute });
}
