// Behavioral test for the meteocons-flat pack's renderIcon. Run with Node's
// built-in runner (no deps):  node --test  (from static/)
//
// The pack reaches the DOM only through the shared core `el` helper (document.
// createElement + className), so it is exercised against a tiny, dependency-free
// DOM stub - just the surface el()/renderIcon touch. Mirrors the weather-icons
// pack test (packs/weather-icons/index.test.js); renderIcon is byte-identical
// across every pack, so only the loaded pack name differs.

import test from "node:test";
import assert from "node:assert/strict";

// ── minimal DOM stub (local, dep-free) ────────────────────────────────────────

/** A stub Element: only the surface core/dom.js el() exercises. */
class El {
  /** @param {string} tag */
  constructor(tag) {
    this.tagName = tag;
    this._classes = new Set();
    this.childNodes = [];
    const self = this;
    this.classList = {
      /** @param {string} c */
      contains: (c) => self._classes.has(c),
    };
  }
  get className() {
    return [...this._classes].join(" ");
  }
  set className(v) {
    this._classes = new Set(String(v).split(/\s+/).filter(Boolean));
  }
  set textContent(v) {
    this.childNodes = [{ textContent: String(v) }];
  }
}

// el() reaches the DOM through the global `document`; wire the stub in before the
// module under test is imported (module top level runs before any test).
globalThis.document = /** @type {any} */ ({ createElement: (tag) => new El(tag) });

const { iconPack } = await import("./index.js");

// ── tests ─────────────────────────────────────────────────────────────────────

test("renderIcon: builds an <i class='wx-icon wx-<name>'> for a condition token", () => {
  const node = iconPack.renderIcon("clear-day");
  assert.equal(node.tagName, "i");
  assert.equal(node.className, "wx-icon wx-clear-day");
  assert.ok(node.classList.contains("wx-icon"), "carries the shared base class");
  assert.ok(node.classList.contains("wx-clear-day"), "carries the per-name class");
});

test("renderIcon: appends the extra class after the name when passed", () => {
  const node = iconPack.renderIcon("wind", "cur-icon");
  assert.equal(node.className, "wx-icon wx-wind cur-icon");
});

test("renderIcon: no trailing space when extra is omitted", () => {
  const node = iconPack.renderIcon("thunderstorm");
  assert.equal(node.className, "wx-icon wx-thunderstorm");
});
