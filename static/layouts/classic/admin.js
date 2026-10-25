// Classic admin skin - the admin screen in the dark-bento glass idiom
// (design-mocks/admin-dark-bento.html). Exports `admin` implementing the
// AdminSkin contract (core/contract.js): mount() builds the shell into
// #admin-root; the render hooks are filled in as each panel lands. Behavior
// (fetch/stage/apply/poll/confirm) lives in core/admin.js, never here.
//
// Every class is `admin-`-prefixed: the overlay shares the document with the
// dashboard, and classic's layout.css styles bare .screen/.glass/.status
// globally.
//
// Side-effect-free on import (the core graph's invariant, see core/machine.js).

import { el } from "../../core/dom.js";
import { BACK_SVG } from "../../core/chrome.js";

/** @typedef {import("../../core/contract.js").AdminCtx} AdminCtx */

// Card-heading glyphs from the mock (trusted own markup).
const APPEARANCE_SVG = '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M4 7h16M4 12h10M4 17h7"/></svg>';
const HEALTH_SVG = '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M3 12h4l2 6 4-14 2 8h6"/></svg>';
const DEVICE_SVG =
  '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M12 2v10"/><path d="M18.4 6.6a9 9 0 1 1-12.8 0"/></svg>';

/**
 * A glass card: icon + uppercase heading, then the id'd panel body the render
 * hooks fill.
 * @param {string} svg @param {string} title @param {string} bodyId @returns {HTMLElement}
 */
function card(svg, title, bodyId) {
  const c = el("section", "admin-card admin-glass");
  const h = el("h2");
  h.innerHTML = svg; // trusted own SVG only
  h.append(title);
  const body = el("div", "admin-panel");
  body.id = bodyId;
  c.append(h, body);
  return c;
}

/** @param {HTMLElement} root @param {AdminCtx} ctx @returns {void} */
function mount(root, ctx) {
  const screen = el("div", "admin-screen");

  const head = el("header", "admin-head");
  const back = el("button", "admin-back");
  back.setAttribute("type", "button");
  back.setAttribute("aria-label", "Back to dashboard");
  back.setAttribute("title", "Back to dashboard");
  back.innerHTML = BACK_SVG;
  back.addEventListener("click", ctx.back); // tap → click (synthesized from wl_touch)
  head.append(back, el("span", "admin-title", "Admin"));

  const body = el("div", "admin-body");
  const right = el("div", "admin-col-right");
  const health = card(HEALTH_SVG, "Device health", "admin-health");
  health.classList.add("admin-grow");
  right.append(health, card(DEVICE_SVG, "Device", "admin-actions"));
  body.append(card(APPEARANCE_SVG, "Appearance", "admin-config"), right);

  screen.append(head, body);
  root.append(screen);
}

// Render hooks - stubs until their panels land (config: Phase 2, stats: Phase 3,
// actions: Phase 4; transition with the apply pipeline).
function renderConfig() {}
function renderStats() {}
function renderActions() {}
function renderTransition() {}

/** @type {import("../../core/contract.js").AdminSkin} */
export const admin = {
  mount,
  renderConfig,
  renderStats,
  renderActions,
  renderTransition,
};
