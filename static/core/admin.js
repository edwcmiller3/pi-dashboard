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

/**
 * @param {AdminSkin} skin the LAYOUT-selected admin skin
 * @param {{ root: HTMLElement }} ctx `root` is the overlay container (#admin-root)
 * @returns {{ open: () => void, close: () => void }}
 */
export function createAdmin(skin, { root }) {
  let mounted = false;

  function open() {
    // Mount lazily and once: the shell persists across open/close.
    if (!mounted) {
      skin.mount(root, { back: () => go("") });
      mounted = true;
    }
    root.hidden = false;
  }

  function close() {
    root.hidden = true;
  }

  return { open, close };
}
