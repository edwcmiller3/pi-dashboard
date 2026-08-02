// The Meteocons LINE icon pack (IconPack, see core/contract.js): maps a semantic
// IconToken (server-resolved weather condition) or a chrome GlyphName (wind /
// humidity / precip / sunrise / sunset) onto a vendored static Meteocons SVG.
// renderIcon builds an <i class="wx-icon wx-<name>"> the line pack.css paints as
// a background-image; `extra` appends a caller class for sizing/color. The name
// is an OWN value (a server-resolved token or a fixed chrome name), so it is safe
// in the class attribute; human text never flows here.
//
// Side-effect-free on import (the core graph invariant, see core/machine.js): the
// DOM is touched only inside renderIcon, via the shared core `el` helper. Loaded
// at runtime by the server's /pack.js route (ICON_PACK setting), not statically
// imported by app.js. renderIcon is byte-identical across every pack; only the
// loaded pack.css differs.

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
