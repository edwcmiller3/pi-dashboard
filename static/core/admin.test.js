// Unit tests for core/admin.js - the layout-agnostic admin controller. Run with
// `node --test` from static/.
//
// The controller only toggles the overlay root and drives an injected skin, so a
// plain-object root and a recording fake skin are enough - no DOM stub.

import test from "node:test";
import assert from "node:assert/strict";

import { createAdmin } from "./admin.js";

/** A fake AdminSkin recording every mount; exposes the ctx it was handed. */
function fakeSkin() {
  const skin = {
    /** @type {{ root: unknown, ctx: any }[]} */
    mounts: [],
    /** @param {unknown} root @param {any} ctx */
    mount(root, ctx) {
      skin.mounts.push({ root, ctx });
    },
    renderConfig() {},
    renderStats() {},
    renderActions() {},
    renderTransition() {},
  };
  return skin;
}

test("admin: open reveals the overlay root; close hides it", () => {
  const root = { hidden: true };
  const admin = createAdmin(fakeSkin(), { root });
  admin.open();
  assert.equal(root.hidden, false);
  admin.close();
  assert.equal(root.hidden, true);
});

test("admin: the skin mounts into the overlay root once, on first open", () => {
  const root = { hidden: true };
  const skin = fakeSkin();
  const admin = createAdmin(skin, { root });
  assert.equal(skin.mounts.length, 0, "constructing must not touch the DOM");
  admin.open();
  admin.close();
  admin.open();
  assert.equal(skin.mounts.length, 1, "re-open reuses the mounted shell");
  assert.equal(skin.mounts[0].root, root);
});

test("admin: the skin's back hook returns to the dashboard route", (t) => {
  const prev = globalThis.location;
  t.after(() => {
    globalThis.location = prev;
  });
  globalThis.location = /** @type {any} */ ({ hash: "#admin" });
  const skin = fakeSkin();
  createAdmin(skin, { root: { hidden: true } }).open();
  skin.mounts[0].ctx.back();
  assert.equal(globalThis.location.hash, "");
});

test("admin: close before any open is harmless", () => {
  const root = { hidden: true };
  const skin = fakeSkin();
  createAdmin(skin, { root }).close();
  assert.equal(root.hidden, true);
  assert.equal(skin.mounts.length, 0);
});
