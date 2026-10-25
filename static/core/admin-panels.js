// Shared admin panel DOM - the config editor and the transition overlay.
//
// The accepted mocks give every live skin identical panel markup (only the CSS
// differs), so it is built once here instead of copied into each skin. A skin
// owns its shell and stylesheet and drops these nodes into its containers.
// Render-only: taps call back into the controller through AdminCtx. Every class
// is `admin-`-prefixed (see layouts/classic/admin.js for why).
//
// Side-effect-free on import (the core graph's invariant, see core/machine.js).

import { el } from "./dom.js";

/** @typedef {import("./contract.js").AdminCtx} AdminCtx */
/** @typedef {import("./contract.js").AdminTransition} AdminTransition */
/** @typedef {import("./contract.js").ConfigKey} ConfigKey */
/** @typedef {import("./contract.js").ConfigKnob} ConfigKnob */
/** @typedef {import("./contract.js").ConfigView} ConfigView */

/** @type {readonly [ConfigKey, string][]} */
const KNOBS = [
  ["layout", "Layout"],
  ["theme", "Theme"],
  ["icon_pack", "Icon pack"],
];

/** THEME "" is the built-in palette. @param {string} value */
const label = (value) => value || "default";

/** @param {string} text @param {string} className @returns {HTMLElement} */
function button(text, className) {
  const b = el("button", className, text);
  b.setAttribute("type", "button");
  return b;
}

/**
 * @param {ConfigKey} key @param {string} name @param {ConfigKnob} knob
 * @param {ConfigView} view @param {AdminCtx} ctx
 */
function knobRow(key, name, knob, view, ctx) {
  const pick = view.staged[key];
  const live = el("span", "admin-knob-live", "Live: ");
  live.append(el("b", null, label(knob.current)));
  const top = el("div", "admin-knob-top");
  top.append(el("span", "admin-knob-name", name), live);

  const opts = el("div", "admin-opts");
  for (const value of knob.options) {
    const opt = /** @type {HTMLButtonElement} */ (button(label(value), "admin-opt"));
    if (value === knob.current) opt.classList.add(pick === undefined ? "admin-current" : "admin-was-current");
    if (value === pick) opt.classList.add("admin-staged");
    opt.setAttribute("aria-pressed", String(value === (pick ?? knob.current)));
    opt.disabled = view.busy;
    opt.addEventListener("click", () => ctx.stage(key, value));
    opts.append(opt);
  }

  const row = el("div", "admin-knob");
  row.append(top, opts);
  return row;
}

/** @param {ConfigView} view @returns {string} */
function summary(view) {
  if (view.busy) return "Applying…";
  if (view.notice) return view.notice.text;
  if (view.pending) return `${view.pending} change${view.pending === 1 ? "" : "s"} staged`;
  return "No changes staged";
}

/** @param {ConfigView} view @param {AdminCtx} ctx */
function applyBar(view, ctx) {
  const text = el("span", "admin-apply-summary", summary(view));
  if (view.notice?.kind === "error") text.classList.add("admin-is-error");
  else if (view.pending || view.busy) text.classList.add("admin-has-staged");

  const on = view.pending > 0 && !view.busy;
  const btn = /** @type {HTMLButtonElement} */ (button("Apply", on ? "admin-apply-btn admin-on" : "admin-apply-btn admin-off"));
  btn.disabled = !on;
  btn.addEventListener("click", () => ctx.apply());

  const bar = el("div", "admin-apply-bar");
  bar.append(text, btn);
  return bar;
}

/**
 * The #admin-config panel body: one row per knob (selection only, no free
 * text) and the Apply bar.
 * @param {ConfigView} view @param {AdminCtx} ctx @returns {HTMLElement[]}
 */
export function configPanel(view, ctx) {
  const { config } = view;
  if (!config) return [el("p", "admin-empty", view.notice?.text ?? "Loading…")];
  return [...KNOBS.map(([key, name]) => knobRow(key, name, config[key], view, ctx)), applyBar(view, ctx)];
}

/** @type {Record<Exclude<AdminTransition, "error">, [string, string]>} */
const COPY = {
  applying: ["Restarting dashboard…", "The display will reload when it's back."],
  rebooting: ["Rebooting…", "The screen will go dark, then return to the dashboard."],
};

/**
 * The full-screen overlay a skin paints over its panels, or null to clear it.
 * @param {AdminTransition | null} state @param {string | undefined} message
 * @param {AdminCtx} ctx @returns {HTMLElement | null}
 */
export function transitionScrim(state, message, ctx) {
  if (!state) return null;
  const term = el("div", "admin-terminal");
  if (state === "error") {
    term.classList.add("admin-is-error");
    const back = button("Back to admin", "admin-dbtn admin-ghost");
    back.addEventListener("click", () => ctx.dismiss());
    term.append(el("div", "admin-big", "Restart didn't finish"), el("div", "admin-small", message ?? ""), back);
  } else {
    const spin = el("div", "admin-spin");
    spin.setAttribute("aria-hidden", "true");
    const [big, small] = COPY[state];
    term.append(spin, el("div", "admin-big", big), el("div", "admin-small", small));
  }
  const scrim = el("div", "admin-scrim");
  scrim.setAttribute("role", "status");
  scrim.append(term);
  return scrim;
}
