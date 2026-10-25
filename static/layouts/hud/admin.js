// HUD admin skin - the admin screen in the green-phosphor instrument idiom
// (design-mocks/admin-instrument-hud.html). Exports `admin` implementing the
// AdminSkin contract (core/contract.js): mount() builds the shell into
// #admin-root; the panel bodies come from core/admin-panels.js (markup shared by
// every skin - only this skin's CSS differs). Behavior lives in core/admin.js.
//
// Every class is `admin-`-prefixed: the overlay shares the document with the
// dashboard, and hud's layout.css styles bare class names globally.
//
// Side-effect-free on import (the core graph's invariant, see core/machine.js).

import { el } from "../../core/dom.js";
import { BACK_SVG } from "../../core/chrome.js";
import { configPanel, healthPanel, transitionScrim } from "../../core/admin-panels.js";

/** @typedef {import("../../core/contract.js").AdminCtx} AdminCtx */
/** @typedef {import("../../core/contract.js").AdminStats} AdminStats */
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
let healthEl = null;
/** @type {HTMLElement | null} */
let scrimEl = null;

/**
 * A bracket panel (two diagonal corner marks) with a ruled uppercase heading,
 * then the id'd panel body the render hooks fill.
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
  right.append(health.card, card("Device", "admin-actions").card);
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

// Stub until its panel lands (Phase 4).
function renderActions() {}

/** @type {import("../../core/contract.js").AdminSkin} */
export const admin = {
  mount,
  renderConfig,
  renderStats,
  renderActions,
  renderTransition,
};
