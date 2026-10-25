// Classic admin skin - the admin screen in the dark-bento glass idiom
// (design-mocks/admin-dark-bento.html). Exports `admin` implementing the
// AdminSkin contract (core/contract.js): mount() builds the shell into
// #admin-root; the panel bodies come from core/admin-panels.js (markup shared by
// every skin - only this skin's CSS differs). Behavior (fetch/stage/apply/poll/
// confirm) lives in core/admin.js, never here.
//
// Every class is `admin-`-prefixed: the overlay shares the document with the
// dashboard, and classic's layout.css styles bare .screen/.glass/.status
// globally.
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

// Card-heading glyphs from the mock (trusted own markup).
const APPEARANCE_SVG = '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M4 7h16M4 12h10M4 17h7"/></svg>';
const HEALTH_SVG = '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M3 12h4l2 6 4-14 2 8h6"/></svg>';
const DEVICE_SVG =
  '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M12 2v10"/><path d="M18.4 6.6a9 9 0 1 1-12.8 0"/></svg>';

/**
 * A glass card: icon + uppercase heading, then the id'd panel body the render
 * hooks fill.
 * @param {string} svg @param {string} title @param {string} bodyId
 * @returns {{ card: HTMLElement, body: HTMLElement }}
 */
function card(svg, title, bodyId) {
  const c = el("section", "admin-card admin-glass");
  const h = el("h2");
  h.innerHTML = svg; // trusted own SVG only
  h.append(title);
  const body = el("div", "admin-panel");
  body.id = bodyId;
  c.append(h, body);
  return { card: c, body };
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
  const health = card(HEALTH_SVG, "Device health", "admin-health").card;
  health.classList.add("admin-grow");
  right.append(health, card(DEVICE_SVG, "Device", "admin-actions").card);
  const config = card(APPEARANCE_SVG, "Appearance", "admin-config");
  body.append(config.card, right);

  screen.append(head, body);
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
