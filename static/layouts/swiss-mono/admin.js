// swiss-mono admin skin (engineering sheet: 1px grid gaps as rules, mono kickers)
// - AdminSkin shell only; panel markup is core/admin-panels.js, behavior
// core/admin.js. Classes are `admin-`-prefixed because the overlay shares the
// document with the dashboard's CSS. Side-effect-free on import.

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
 * A grid cell with a kicker heading over the id'd panel body; `area` places it.
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

  const config = panel("Appearance", "admin-config", "admin-area-config");
  const health = panel("Device health", "admin-health", "admin-area-health");
  const actions = panel("Device", "admin-actions", "admin-area-actions");
  screen.append(
    head,
    config.cell,
    health.cell,
    actions.cell,
  );
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
