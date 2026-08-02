// The weather-icons reference icon pack (IconPack, see core/contract.js): maps a
// semantic IconToken (server-resolved weather condition) or a chrome GlyphName
// (wind / humidity / precip / sunrise / sunset) onto a self-hosted subset
// weather-icons glyph. renderIcon builds an <i class="wx-icon wx-<name>"> whose
// ::before content (pack.css) draws the glyph; `extra` appends a caller class for
// sizing/color. The name is an OWN value (a server-resolved token or a fixed
// chrome name), so it is safe in the class attribute; human text never flows here.
//
// Side-effect-free on import (the core graph invariant, see core/machine.js): the
// DOM is touched only inside renderIcon, via the shared core `el` helper. Loaded
// at runtime by the server's /pack.js route (ICON_PACK setting; this is the
// default pack), not statically imported by app.js.

import { el } from "../../core/dom.js";

/** @type {import("../../core/contract.js").IconPack} */
export const iconPack = {
  /**
   * @param {import("../../core/contract.js").IconToken | import("../../core/contract.js").GlyphName} name
   * @param {string} [extra]
   * @returns {HTMLElement}
   */
  renderIcon(name, extra) {
    return el("i", "wx-icon wx-" + name + (extra ? " " + extra : ""));
  },
};
