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
import { layout } from "/layout.js";
import { iconPack } from "/pack.js";

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
}
