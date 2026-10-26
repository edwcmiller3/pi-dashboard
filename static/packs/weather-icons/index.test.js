// Behavioral test for the weather-icons pack's renderIcon. The pack touches the
// DOM only via core `el` (createElement + className), so a minimal stub
// suffices.

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

// el() reads the global `document`; install the stub before importing the pack.
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
