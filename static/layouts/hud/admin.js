// HUD admin skin (green-phosphor instrument) - AdminSkin shell only; panel markup
// is core/admin-panels.js, behavior core/admin.js. Classes are `admin-`-prefixed
// because the overlay shares the document with the dashboard's CSS.
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

/**
 * A bracket panel with a ruled heading over the id'd panel body.
 * @param {string} title @param {string} bodyId
 * @returns {{ card: HTMLElement, body: HTMLElement }}
 */
function card(title, bodyId) {
  const c = el("section", "admin-card");
  const body = el("div", "admin-panel");
  body.id = bodyId;
  c.append(el("h2", null, title), body);
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
  const health = card("Device health", "admin-health");
  health.card.classList.add("admin-grow");
  const actions = card("Device", "admin-actions");
  right.append(health.card, actions.card);
  const config = card("Appearance", "admin-config");
  body.append(config.card, right);

  // Static CRT dressing (scanlines + vignette), above the panels.
  const fx = el("div", "admin-fx");
  fx.setAttribute("aria-hidden", "true");

  screen.append(head, body, fx);
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
