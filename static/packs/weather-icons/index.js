// weather-icons font pack (IconPack, see core/contract.js), the default; pack.css
// draws each .wx-<name> via ::before. `name` is a server/fixed token, never user
// text, so it is safe in the class attribute.

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
