// Hash router for overlay screens: `#<name>` opens a route, any other hash is the
// dashboard. The window is injectable so node:test can drive a fake.

/**
 * @typedef {object} Route
 * @property {() => void} open activate the screen (may be async; not awaited)
 * @property {() => void} close deactivate it
 */

/** @typedef {Pick<Window, "location" | "history" | "addEventListener">} RouterWindow */

/**
 * Boot always lands on the dashboard: an initial hash is cleared, not dispatched,
 * so a reload never strands the wall on a control screen.
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
