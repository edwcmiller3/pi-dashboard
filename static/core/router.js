// Core hash router - the minimal routing primitive overlay screens mount into.
//
// A route is a named screen with open/close hooks; `#<name>` activates it and
// any other hash (including none) is the dashboard. Deliberately map-driven, not
// admin-specific, so later screens register alongside admin.
//
// Side-effect-free on import (the core graph's invariant, see core/machine.js):
// the window is touched only when onRoute()/go() are called, and is injectable
// so node:test can drive a fake.

/**
 * @typedef {object} Route
 * @property {() => void} open activate the screen (may be async; not awaited)
 * @property {() => void} close deactivate it
 */

/** @typedef {Pick<Window, "location" | "history" | "addEventListener">} RouterWindow */

/**
 * Wire `routes` to the location hash. Boot always lands on the dashboard: an
 * initial hash (a reload or cold boot while a screen was open) is cleared, not
 * dispatched - the wall must never come up stranded on a control screen.
 * @param {Record<string, Route>} routes keyed by hash name, without the '#'
 * @param {RouterWindow} [win]
 * @returns {void}
 */
export function onRoute(routes, win = globalThis) {
  /** @type {string | null} */
  let active = null;

  function dispatch() {
    const name = win.location.hash.replace(/^#/, "");
    // hasOwn, not `in`: "#constructor" must not resolve to Object.prototype.
    const next = Object.hasOwn(routes, name) ? name : null;
    if (next === active) return;
    if (active !== null) routes[active].close();
    active = next;
    if (next !== null) routes[next].open();
  }

  // replaceState, not `hash = ""`: no extra history entry and no hashchange.
  if (win.location.hash) {
    win.history.replaceState(null, "", win.location.pathname + win.location.search);
  }
  win.addEventListener("hashchange", dispatch);
}

/**
 * Navigate to a route by name; "" returns to the dashboard.
 * @param {string} name
 * @param {Pick<Window, "location">} [win]
 * @returns {void}
 */
export function go(name, win = globalThis) {
  win.location.hash = name;
}
