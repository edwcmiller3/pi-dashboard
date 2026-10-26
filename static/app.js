// Entry point: wires the core state machine to the layout and icon pack, which
// the server selects via the /layout.js and /pack.js routes (LAYOUT / ICON_PACK).
// The pack is injected through createApp's ctx so a layout never names a pack.

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

// Admin is rarely opened, so it stays out of the boot graph and loads on first
// open. Cached; a failed load is dropped so the next tap retries.
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

// Guarded so importing under node:test has no DOM side effects. Fail-soft: a
// layout throwing on mount must not kill the wall display.
if (typeof document !== "undefined") {
  try {
    createApp(layout, { icon: iconPack }).init();
  } catch (err) {
    console.error("layout failed to mount:", err);
  }
  onRoute({ admin: adminRoute });
}
