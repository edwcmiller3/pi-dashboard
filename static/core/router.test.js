// Unit tests for core/router.js. The router takes its window surface as an
// argument, so a fake (location + history + hashchange registry) suffices.

import test from "node:test";
import assert from "node:assert/strict";

import { onRoute, go } from "./router.js";

/** A fake window: settable hash, recorded replaceState calls, fireable hashchange. */
function fakeWin(hash = "") {
  /** @type {(() => void)[]} */
  const listeners = [];
  /** @type {string[]} */
  const replaced = [];
  const win = {
    location: { hash, pathname: "/", search: "" },
    history: {
      /** @param {unknown} _s @param {string} _t @param {string} url */
      replaceState(_s, _t, url) {
        replaced.push(url);
        win.location.hash = "";
      },
    },
    /** @param {string} type @param {() => void} fn */
    addEventListener(type, fn) {
      if (type === "hashchange") listeners.push(fn);
    },
    replaced,
    /** @param {string} h */
    navigate(h) {
      win.location.hash = h;
      for (const fn of listeners) fn();
    },
  };
  return win;
}

/** A route that records its open/close calls in order. */
function spyRoute(log, name) {
  return { open: () => log.push(`open:${name}`), close: () => log.push(`close:${name}`) };
}

test("router: #admin dispatches open; leaving it dispatches close", () => {
  const win = fakeWin();
  const log = [];
  onRoute({ admin: spyRoute(log, "admin") }, win);
  win.navigate("#admin");
  win.navigate("");
  assert.deepEqual(log, ["open:admin", "close:admin"]);
});

test("router: an unknown hash is the dashboard (closes the active route)", () => {
  const win = fakeWin();
  const log = [];
  onRoute({ admin: spyRoute(log, "admin") }, win);
  win.navigate("#admin");
  win.navigate("#nope");
  assert.deepEqual(log, ["open:admin", "close:admin"]);
});

test("router: re-dispatching the active route is a no-op (no double open)", () => {
  const win = fakeWin();
  const log = [];
  onRoute({ admin: spyRoute(log, "admin") }, win);
  win.navigate("#admin");
  win.navigate("#admin");
  win.navigate("");
  win.navigate("");
  assert.deepEqual(log, ["open:admin", "close:admin"]);
});

test("router: switching between two routes closes the old before opening the new", () => {
  const win = fakeWin();
  const log = [];
  onRoute({ admin: spyRoute(log, "admin"), calendar: spyRoute(log, "calendar") }, win);
  win.navigate("#admin");
  win.navigate("#calendar");
  assert.deepEqual(log, ["open:admin", "close:admin", "open:calendar"]);
});

test("router: boot clears an initial #admin to the dashboard without opening it", () => {
  const win = fakeWin("#admin");
  const log = [];
  onRoute({ admin: spyRoute(log, "admin") }, win);
  assert.deepEqual(log, [], "a reload/cold boot onto #admin must land on the dashboard");
  assert.equal(win.location.hash, "");
  assert.deepEqual(win.replaced, ["/"], "cleared via replaceState (no history entry)");
  // ...and the route still works afterwards.
  win.navigate("#admin");
  assert.deepEqual(log, ["open:admin"]);
});

test("router: boot with no hash leaves history untouched", () => {
  const win = fakeWin();
  onRoute({ admin: spyRoute([], "admin") }, win);
  assert.deepEqual(win.replaced, []);
});

test("router: a prototype key in the hash is not a route", () => {
  const win = fakeWin();
  const log = [];
  onRoute({ admin: spyRoute(log, "admin") }, win);
  assert.doesNotThrow(() => win.navigate("#constructor"));
  assert.deepEqual(log, []);
});

test("go: sets the hash to the named route ('' = dashboard)", () => {
  const win = fakeWin();
  go("admin", win);
  assert.equal(win.location.hash, "admin");
  go("", win);
  assert.equal(win.location.hash, "");
});
