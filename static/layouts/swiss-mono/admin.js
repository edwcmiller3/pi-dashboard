// swiss-mono admin skin - the admin screen in the engineering-sheet idiom
// (design-mocks/admin-swiss-mono.html): an exposed modular grid whose 1px ink
// gaps read as drafted rules, mono kickers in place of card headings. Exports
// `admin` implementing the AdminSkin contract (core/contract.js): mount() builds
// the shell into #admin-root; the panel bodies come from core/admin-panels.js
// (markup shared by every skin - only this skin's CSS differs). Behavior lives
// in core/admin.js.
//
// Every class is `admin-`-prefixed: the overlay shares the document with the
// dashboard, and swiss-mono's layout.css styles bare .cell/.screen globally.
//
// Side-effect-free on import (the core graph's invariant, see core/machine.js).

import { el } from "../../core/dom.js";
import { BACK_SVG } from "../../core/chrome.js";
import { configPanel, transitionScrim } from "../../core/admin-panels.js";

/** @typedef {import("../../core/contract.js").AdminCtx} AdminCtx */
/** @typedef {import("../../core/contract.js").AdminTransition} AdminTransition */
/** @typedef {import("../../core/contract.js").ConfigView} ConfigView */

// Built once per mount (the controller mounts once); the render hooks fill them.
/** @type {AdminCtx | null} */
let adminCtx = null;
/** @type {HTMLElement | null} */
let screenEl = null;
/** @type {HTMLElement | null} */
let configEl = null;
/** @type {HTMLElement | null} */
let scrimEl = null;

/**
 * A grid cell carrying a numbered mono kicker, then the id'd panel body the
 * render hooks fill. `area` places it in the screen grid.
 * @param {string} kicker @param {string} bodyId @param {string} area
 * @returns {{ cell: HTMLElement, body: HTMLElement }}
 */
function panel(kicker, bodyId, area) {
  const cell = el("section", `admin-cell admin-panel-cell ${area}`);
  const body = el("div", "admin-panel");
  body.id = bodyId;
  cell.append(el("h2", "admin-kick", kicker), body);
  return { cell, body };
}

/** @param {HTMLElement} root @param {AdminCtx} ctx @returns {void} */
function mount(root, ctx) {
  const screen = el("div", "admin-screen");

  const head = el("header", "admin-cell admin-head");
  const back = el("button", "admin-back");
  back.setAttribute("type", "button");
  back.setAttribute("aria-label", "Back to dashboard");
  back.setAttribute("title", "Back to dashboard");
  back.innerHTML = BACK_SVG;
  back.addEventListener("click", ctx.back); // tap → click (synthesized from wl_touch)
  head.append(back, el("span", "admin-title", "Admin"));

  const config = panel("01 / Config", "admin-config", "admin-area-config");
  screen.append(
    head,
    config.cell,
    panel("02 / Device health", "admin-health", "admin-area-health").cell,
    panel("03 / Device", "admin-actions", "admin-area-actions").cell,
  );
  root.append(screen);
  adminCtx = ctx;
  screenEl = screen;
  configEl = config.body;
}

/** @param {ConfigView} view */
function renderConfig(view) {
  if (configEl && adminCtx) configEl.replaceChildren(...configPanel(view, adminCtx));
}

/** @param {AdminTransition | null} state @param {string} [message] */
function renderTransition(state, message) {
  if (!screenEl || !adminCtx) return;
  scrimEl?.remove();
  scrimEl = transitionScrim(state, message, adminCtx);
  if (scrimEl) screenEl.append(scrimEl);
}

// Stubs until their panels land (stats: Phase 3, actions: Phase 4).
function renderStats() {}
function renderActions() {}

/** @type {import("../../core/contract.js").AdminSkin} */
export const admin = {
  mount,
  renderConfig,
  renderStats,
  renderActions,
  renderTransition,
};
