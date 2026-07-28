// Pi Dashboard entry point — the thin bootstrap that wires the layout-agnostic
// core state machine to a concrete layout, then boots it in the browser.
//
// The concrete layout comes from the server's /layout.js route (a generated
// one-line re-export of the LAYOUT-selected module — classic by default), so
// selection is server-side config, mirroring the theme mechanism. The stable
// entry name (app.js) keeps index.html's <script> and the static-freshness
// tests unchanged.

import { createApp } from "./core/machine.js";
import { layout } from "/layout.js";

// Browser-only bootstrap. Guarded so importing the module graph under node:test
// (for the pure-function unit tests) runs no DOM/init side effects. Fail-soft:
// a layout that throws on mount must not leave an unhandled error — the plan's
// blank-kiosk mitigation. Classic must never throw in practice; this is the net
// that lets a later, riskier layout degrade instead of killing the wall display.
if (typeof document !== "undefined") {
  try {
    createApp(layout).init();
  } catch (err) {
    console.error("layout failed to mount:", err);
  }
}
