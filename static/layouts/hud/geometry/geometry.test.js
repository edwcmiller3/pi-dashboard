// Unit tests for the pure HUD geometry modules.
// Run standalone:  node --test static/layouts/hud/geometry/geometry.test.js
//
// These modules are DOM-free, so importing them runs no side effects - only
// the pure exports load. Assertions are EXACT hand-computed values, cross-
// checked against design-mocks/instrument-hud-d.html (July fixture) and
// instrument-hud-d-winter.html (SCALE 10–50). Following app.test.js, `// @ts-check`
// is intentionally NOT enabled (zero deps → TS can't resolve node:* builtins).

import test from "node:test";
import assert from "node:assert/strict";

import { computeScaleWindow } from "./scale.js";
import {
  polarPoint,
  angleForValue,
  arcPath,
  dialGeometry,
  DEFAULT_DIAL_CONFIG,
} from "./dial.js";
import { solarGeometry } from "./solar.js";
import {
  scalePct,
  forecastRangePlot,
  forecastRuler,
  rulerDivisions,
} from "./forecast.js";

/** Assert two floats are equal within eps (default 1e-9). */
function close(actual, expected, eps = 1e-9, msg) {
  assert.ok(
    Math.abs(actual - expected) <= eps,
    msg || `expected ${actual} ≈ ${expected} (±${eps})`,
  );
}

// The mock's July fixture: today cur/hi/lo + four forecast days' lo/hi.
const JULY_TEMPS = [82, 88, 71, 72, 90, 70, 84, 66, 78, 68, 81];
const JULY_WINDOW = { min: 60, max: 100 };
// The winter mock's fixture (instrument-hud-d-winter.html).
const WINTER_TEMPS = [28, 34, 21, 18, 29, 11, 27, 19, 31, 24, 36];
const WINTER_WINDOW = { min: 10, max: 50 };

// ── computeScaleWindow ───────────────────────────────────────────────────────

test("computeScaleWindow: July fixture → {60,100} (matches mock comment)", () => {
  assert.deepEqual(computeScaleWindow(JULY_TEMPS), JULY_WINDOW);
});

test("computeScaleWindow: winter fixture → {10,50} (matches winter mock)", () => {
  assert.deepEqual(computeScaleWindow(WINTER_TEMPS), WINTER_WINDOW);
});

test("computeScaleWindow: lo exactly on a gridline drops one full step", () => {
  // min(70) snaps to 70, equals lo → step down to 60; span holds 90.
  assert.deepEqual(computeScaleWindow([70, 90]), { min: 60, max: 100 });
});

test("computeScaleWindow: spread wider than span widens the window", () => {
  // lo 50 → floor 50 == lo → 40; max 80 < hi 100 → ceil 100 == hi → 110;
  // min held at 40 (covers lo). Span becomes 70.
  assert.deepEqual(computeScaleWindow([50, 100]), { min: 40, max: 110 });
});

test("computeScaleWindow: hi off-gridline ceils up, min recomputed", () => {
  // lo 60 → 50; max 90 <= hi 105 → ceil 110 (105 not on grid); min(50,70)=50.
  assert.deepEqual(computeScaleWindow([60, 105]), { min: 50, max: 110 });
});

test("computeScaleWindow: custom span/step honored", () => {
  assert.deepEqual(computeScaleWindow([32, 60], 60, 10), { min: 30, max: 90 });
});

test("computeScaleWindow: single off-gridline temp → default-span window around it", () => {
  // lo=hi=72 → floor 70 (≠72) → max 70+40; hi 72 < 110, no widen.
  assert.deepEqual(computeScaleWindow([72]), { min: 70, max: 110 });
});

test("computeScaleWindow: all-equal temps on a gridline drop one full step", () => {
  // lo=hi=80 → floor 80 == lo → step down to 70; max 70+40; hi 80 < 110.
  assert.deepEqual(computeScaleWindow([80, 80, 80]), { min: 70, max: 110 });
});

test("computeScaleWindow: empty array pins to {Infinity, Infinity} (degenerate, no crash)", () => {
  // min(...[])=Infinity, max(...[])=-Infinity → floor(Inf)*step=Inf, ==lo so -step=Inf,
  // max=Inf+span=Inf; hi(-Inf) >= max(Inf) is false → {Infinity, Infinity}. Not NaN,
  // does not throw. Pinned so the degenerate output is documented, not relied on silently.
  const w = computeScaleWindow([]);
  assert.deepEqual(w, { min: Infinity, max: Infinity });
  assert.equal(Number.isNaN(w.min), false);
  assert.equal(Number.isNaN(w.max), false);
});

// ── dial: primitives ─────────────────────────────────────────────────────────

test("angleForValue: min→-120, max→+120, midpoint→0 (240° sweep)", () => {
  assert.equal(angleForValue(60, 60, 100), -120);
  assert.equal(angleForValue(100, 60, 100), 120);
  assert.equal(angleForValue(80, 60, 100), 0);
});

test("angleForValue: July value 82 → 12°, winter value 28 → -12°", () => {
  assert.equal(angleForValue(82, 60, 100), 12);
  assert.equal(angleForValue(28, 10, 50), -12);
});

test("polarPoint: 0° is straight up from center", () => {
  const p = polarPoint(290, 146, 118, 0);
  close(p.x, 290);
  close(p.y, 146 - 118); // 28
});

test("polarPoint: -120° matches mock arc-start coordinates", () => {
  const p = polarPoint(290, 146, 118, -120);
  close(p.x, 187.809, 1e-3);
  close(p.y, 205); // cos(-120°) = -0.5 → 146 + 59
});

test("arcPath: baseline sweep path string is byte-exact (July)", () => {
  const path = arcPath(290, 146, 118, -120, 120);
  assert.equal(path, "M187.81 205.00 A118 118 0 1 1 392.19 205.00");
});

test("arcPath: value sweep -120→12 is byte-exact (July, small arc)", () => {
  const path = arcPath(290, 146, 118, -120, 12);
  assert.equal(path, "M187.81 205.00 A118 118 0 0 1 314.53 30.58");
});

test("arcPath: exactly-180° sweep is NOT large (a2-a1===180 → flag 0)", () => {
  // boundary of `a2 - a1 > 180`: equal-to-180 must stay on the small-arc branch
  const path = arcPath(290, 146, 118, -90, 90);
  assert.equal(path, "M172.00 146.00 A118 118 0 0 1 408.00 146.00");
  assert.equal(path.split(" ")[5], "0"); // large-arc-flag byte
});

test("arcPath: sweep exceeding 180° is large (flag 1)", () => {
  // -120→108 = 228° > 180 → large-arc branch
  const path = arcPath(290, 146, 118, -120, 108);
  assert.equal(path, "M187.81 205.00 A118 118 0 1 1 402.22 182.46");
  assert.equal(path.split(" ")[5], "1"); // large-arc-flag byte
});

// ── dial: composite geometry ─────────────────────────────────────────────────

test("dialGeometry: July value 82 on {60,100} — angle, arcs, endpoint", () => {
  const g = dialGeometry(82, JULY_WINDOW);
  assert.equal(g.angle, 12);
  assert.equal(g.value, 82);
  assert.deepEqual(g.center, { x: 290, y: 146 });
  assert.equal(g.radius, 118);
  assert.equal(g.baselineArc, "M187.81 205.00 A118 118 0 1 1 392.19 205.00");
  assert.equal(g.valueArc, "M187.81 205.00 A118 118 0 0 1 314.53 30.58");
  // arc endpoint at 12° = the value indicator
  close(g.valuePoint.x, 314.53358, 1e-4);
  close(g.valuePoint.y, 30.57858, 1e-4);
});

test("dialGeometry: ticks every 5°, majors every 10° with numerals", () => {
  const g = dialGeometry(82, JULY_WINDOW);
  // 60..100 step 5 → 9 ticks
  assert.equal(g.ticks.length, 9);
  assert.deepEqual(
    g.ticks.map((t) => t.value),
    [60, 65, 70, 75, 80, 85, 90, 95, 100],
  );
  // majors are the %10 gridlines and carry a numeral
  const majors = g.ticks.filter((t) => t.major);
  assert.deepEqual(
    majors.map((t) => t.label.text),
    ["60", "70", "80", "90", "100"],
  );
  // minors carry no label
  assert.equal(
    g.ticks.filter((t) => !t.major).every((t) => t.label === null),
    true,
  );
  // first tick sits at the -120° start; label baseline nudged +4 (mock)
  const first = g.ticks[0];
  assert.equal(first.value, 60);
  assert.equal(first.major, true);
  assert.equal(first.angle, -120);
  const labelBase = polarPoint(290, 146, DEFAULT_DIAL_CONFIG.labelR, -120);
  close(first.label.y, labelBase.y + 4);
});

test("dialGeometry: hot day 98 on {60,100} — value arc exceeds 180° (large flag)", () => {
  // angle 108° → value sweep -120→108 = 228° > 180 → valueArc large-arc-flag 1
  const g = dialGeometry(98, JULY_WINDOW);
  assert.equal(g.angle, 108);
  assert.equal(g.valueArc, "M187.81 205.00 A118 118 0 1 1 402.22 182.46");
  assert.equal(g.valueArc.split(" ")[5], "1");
});

test("dialGeometry: winter value 28 on {10,50} — angle -12° (arc sweeps correctly)", () => {
  const g = dialGeometry(28, WINTER_WINDOW);
  assert.equal(g.angle, -12);
  assert.equal(g.ticks.length, 9); // 10..50 step 5
  assert.deepEqual(
    g.ticks.filter((t) => t.major).map((t) => t.label.text),
    ["10", "20", "30", "40", "50"],
  );
});

// ── solar tape ───────────────────────────────────────────────────────────────

test("solarGeometry: clean fixture (6:00→18:00, noon) → fraction 0.5, nowX 270", () => {
  const s = solarGeometry({ sunriseMin: 360, sunsetMin: 1080, nowMin: 720 });
  assert.equal(s.fraction, 0.5);
  assert.equal(s.daylightMinutes, 720);
  assert.equal(s.nowX, 270);
  assert.equal(s.sunMarker.cx, 270);
  assert.equal(s.sunMarker.cy, 20);
  // cross ticks offset from center (270,20) by the mock's ~25%-smaller set
  assert.deepEqual(s.sunMarker.crossTicks[0], { x1: 270, y1: 12, x2: 270, y2: 14.5 });
  assert.deepEqual(s.sunMarker.crossTicks[2], { x1: 262, y1: 20, x2: 264.5, y2: 20 });
  // sunrise/sunset bugs are vertical, ±6 about the tape line
  assert.deepEqual(s.bugs[0], { x1: 52, y1: 14, x2: 52, y2: 26 });
  assert.deepEqual(s.bugs[1], { x1: 488, y1: 14, x2: 488, y2: 26 });
  // dashed baseline spans the full viewBox
  assert.deepEqual(s.baseline, { x1: 8, y1: 20, x2: 544, y2: 20 });
});

test("solarGeometry: idle ticks — 22 evenly spaced from x=16 to x=520", () => {
  const s = solarGeometry({ sunriseMin: 360, sunsetMin: 1080, nowMin: 720 });
  assert.equal(s.idleTicks.length, 22);
  assert.equal(s.idleTicks[0].x1, 16);
  assert.equal(s.idleTicks[s.idleTicks.length - 1].x1, 520);
  assert.deepEqual(s.idleTicks[0], { x1: 16, y1: 20, x2: 16, y2: 24 });
});

test("solarGeometry: July fixture (5:47→20:29, 14:46) matches mock t = 539/882", () => {
  // sunrise 347 min, sunset 1229 min, now 886 min
  const s = solarGeometry({ sunriseMin: 347, sunsetMin: 1229, nowMin: 886 });
  assert.equal(s.daylightMinutes, 882); // 14h 42m
  close(s.fraction, 539 / 882, 1e-12);
  close(s.nowX, 52 + 436 * (539 / 882), 1e-9); // ≈ 318.4444
});

test("solarGeometry: fraction is raw/unclamped (night → outside [0,1])", () => {
  // now before sunrise → negative fraction, nowX left of the tape start
  const s = solarGeometry({ sunriseMin: 360, sunsetMin: 1080, nowMin: 300 });
  close(s.fraction, (300 - 360) / (1080 - 360)); // -0.08333…
  assert.ok(s.nowX < s.sunriseX);
});

// ── forecast range plot ──────────────────────────────────────────────────────

test("scalePct: floor→0%, ceil→100%, midpoint→50%", () => {
  assert.equal(scalePct(60, JULY_WINDOW), 0);
  assert.equal(scalePct(100, JULY_WINDOW), 100);
  assert.equal(scalePct(80, JULY_WINDOW), 50);
});

test("forecastRangePlot: July four days on {60,100} — exact marker percents", () => {
  const days = [
    { low_f: 72, high_f: 90 }, // SUN
    { low_f: 70, high_f: 84 }, // MON
    { low_f: 66, high_f: 78 }, // TUE
    { low_f: 68, high_f: 81 }, // WED
  ];
  assert.deepEqual(forecastRangePlot(days, JULY_WINDOW), [
    { loPct: 30, hiPct: 75, linkLeftPct: 30, linkWidthPct: 45 },
    { loPct: 25, hiPct: 60, linkLeftPct: 25, linkWidthPct: 35 },
    { loPct: 15, hiPct: 45, linkLeftPct: 15, linkWidthPct: 30 },
    { loPct: 20, hiPct: 52.5, linkLeftPct: 20, linkWidthPct: 32.5 },
  ]);
});

test("forecastRangePlot: winter day on {10,50} — coldest reading stays off the edge", () => {
  // window floor 10 gives headroom below the coldest lo (11) → 2.5%, not 0%
  assert.deepEqual(forecastRangePlot([{ low_f: 11, high_f: 36 }], WINTER_WINDOW), [
    { loPct: 2.5, hiPct: 65, linkLeftPct: 2.5, linkWidthPct: 62.5 },
  ]);
});

test("forecastRuler: numerals every 20° from the floor, with percents", () => {
  assert.deepEqual(forecastRuler(JULY_WINDOW), [
    { value: 60, pct: 0 },
    { value: 80, pct: 50 },
    { value: 100, pct: 100 },
  ]);
  assert.deepEqual(forecastRuler(WINTER_WINDOW), [
    { value: 10, pct: 0 },
    { value: 30, pct: 50 },
    { value: 50, pct: 100 },
  ]);
});

test("rulerDivisions: span / 5 minor divisions", () => {
  assert.equal(rulerDivisions(JULY_WINDOW), 8);
  assert.equal(rulerDivisions({ min: 40, max: 110 }), 14);
});
