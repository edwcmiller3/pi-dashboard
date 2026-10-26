// Classic admin skin (dark-bento glass) - AdminSkin shell only; panel markup is
// core/admin-panels.js, behavior core/admin.js. Classes are `admin-`-prefixed
// because classic's layout.css styles bare .screen/.glass globally.
// Side-effect-free on import.

import { el } from "../../core/dom.js";
import { BACK_SVG } from "../../core/chrome.js";
import { actionsPanel, configPanel, confirmDialog, healthPanel, transitionScrim } from "../../core/admin-panels.js";

/** @typedef {import("../../core/contract.js").ActionsView} ActionsView */
/** @typedef {import("../../core/contract.js").AdminCtx} AdminCtx */
/** @typedef {import("../../core/contract.js").AdminStats} AdminStats */
/** @typedef {import("../../core/contract.js").AdminTransition} AdminTransition */
/** @typedef {import("../../core/contract.js").ConfigView} ConfigView */

// Set once in mount(); the render hooks fill them.
/** @type {AdminCtx | null} */
let adminCtx = null;
/** @type {HTMLElement | null} */
let screenEl = null;
/** @type {HTMLElement | null} */
let configEl = null;
/** @type {HTMLElement | null} */
let healthEl = null;
/** @type {HTMLElement | null} */
let actionsEl = null;
/** @type {HTMLElement | null} */
let dialogEl = null;
/** @type {HTMLElement | null} */
let scrimEl = null;

// Card-heading glyphs (trusted own markup).
const APPEARANCE_SVG = '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M4 7h16M4 12h10M4 17h7"/></svg>';
const HEALTH_SVG = '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M3 12h4l2 6 4-14 2 8h6"/></svg>';
const DEVICE_SVG =
  '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M12 2v10"/><path d="M18.4 6.6a9 9 0 1 1-12.8 0"/></svg>';

/**
 * A glass card with an icon heading over the id'd panel body.
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
  const health = card(HEALTH_SVG, "Device health", "admin-health");
  health.card.classList.add("admin-grow");
  const actions = card(DEVICE_SVG, "Device", "admin-actions");
  right.append(health.card, actions.card);
  const config = card(APPEARANCE_SVG, "Appearance", "admin-config");
  body.append(config.card, right);

  screen.append(head, body);
  root.append(screen);
  adminCtx = ctx;
  screenEl = screen;
  configEl = config.body;
  healthEl = health.body;
  actionsEl = actions.body;
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

/** @param {AdminStats | null} stats */
function renderStats(stats) {
  healthEl?.replaceChildren(...healthPanel(stats));
}

/** @param {ActionsView} view */
function renderActions(view) {
  if (!screenEl || !actionsEl || !adminCtx) return;
  actionsEl.replaceChildren(...actionsPanel(view, adminCtx));
  dialogEl?.remove();
  dialogEl = confirmDialog(view, adminCtx);
  // Before any transition scrim, so a transition always paints on top.
  if (dialogEl) screenEl.insertBefore(dialogEl, scrimEl);
}

/** @type {import("../../core/contract.js").AdminSkin} */
export const admin = {
  mount,
  renderConfig,
  renderStats,
  renderActions,
  renderTransition,
};
