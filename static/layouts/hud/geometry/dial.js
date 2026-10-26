// HUD geometry - 240° temperature dial: angles, arc paths and tick specs. Pure,
// DOM-free. Math and DialConfig defaults from the PRIMARY TEMP DIAL block in
// design-mocks/instrument-hud.html.

/**
 * @typedef {object} Point
 * @property {number} x
 * @property {number} y
 */

/**
 * @typedef {object} DialConfig
 * @property {number} cx dial center x
 * @property {number} cy dial center y
 * @property {number} radius arc radius
 * @property {number} sweep total angular sweep in degrees
 * @property {number} tickStep °F between ticks
 * @property {number} majorStep °F between major ticks + numerals
 * @property {number} tickOuterR outer radius of every tick
 * @property {number} majorInnerR inner radius of a major tick
 * @property {number} minorInnerR inner radius of a minor tick
 * @property {number} labelR radius of the numeral ring
 */

/** @type {DialConfig} */
export const DEFAULT_DIAL_CONFIG = {
  cx: 290,
  cy: 146,
  radius: 118,
  sweep: 240,
  tickStep: 5,
  majorStep: 10,
  tickOuterR: 112,
  majorInnerR: 94,
  minorInnerR: 102,
  labelR: 82,
};

/**
 * A single dial tick with its optional numeral.
 * @typedef {object} DialTick
 * @property {number} value the °F this tick marks
 * @property {boolean} major true on a `majorStep` gridline (longer, labelled)
 * @property {number} angle degrees clockwise from 12 o'clock
 * @property {Point} outer outer end of the tick line
 * @property {Point} inner inner end of the tick line
 * @property {(Point & {text: string}) | null} label numeral pos+text, or null
 */

/**
 * @typedef {object} DialGeometry
 * @property {number} value the temperature being displayed
 * @property {number} angle needle/value angle (deg clockwise from 12 o'clock);
 *   there is no discrete needle - the value arc's terminal point IS the indicator
 * @property {Point} center dial center
 * @property {number} radius arc radius
 * @property {Point} valuePoint arc endpoint at `value` - the value indicator
 * @property {string} baselineArc SVG path, full min→max sweep
 * @property {string} valueArc SVG path, min→value sweep
 * @property {DialTick[]} ticks
 */

/**
 * Polar → cartesian, degrees clockwise from 12 o'clock.
 * @param {number} cx
 * @param {number} cy
 * @param {number} r
 * @param {number} deg
 * @returns {Point}
 */
export function polarPoint(cx, cy, r, deg) {
  const a = (deg * Math.PI) / 180;
  return { x: cx + r * Math.sin(a), y: cy - r * Math.cos(a) };
}

/**
 * Temperature → dial angle, centered on 12 o'clock: min → -sweep/2, max → +sweep/2.
 * @param {number} value
 * @param {number} min
 * @param {number} max
 * @param {number} [sweep=240]
 * @returns {number} degrees clockwise from 12 o'clock
 */
export function angleForValue(value, min, max, sweep = DEFAULT_DIAL_CONFIG.sweep) {
  return -sweep / 2 + (sweep * (value - min)) / (max - min);
}

/**
 * SVG arc path between two angles; endpoints rounded to 2 decimals so path
 * strings are byte-reproducible.
 * @param {number} cx
 * @param {number} cy
 * @param {number} r
 * @param {number} a1 start angle (deg cw from 12 o'clock)
 * @param {number} a2 end angle
 * @returns {string}
 */
export function arcPath(cx, cy, r, a1, a2) {
  const p1 = polarPoint(cx, cy, r, a1);
  const p2 = polarPoint(cx, cy, r, a2);
  const large = a2 - a1 > 180 ? 1 : 0;
  return (
    "M" +
    p1.x.toFixed(2) +
    " " +
    p1.y.toFixed(2) +
    " A" +
    r +
    " " +
    r +
    " 0 " +
    large +
    " 1 " +
    p2.x.toFixed(2) +
    " " +
    p2.y.toFixed(2)
  );
}

/**
 * @param {number} value temperature to display
 * @param {import("./scale.js").ScaleWindow} scaleWindow shared scale window
 * @param {Partial<DialConfig>} [config] overrides for the mock defaults
 * @returns {DialGeometry}
 */
export function dialGeometry(value, scaleWindow, config = {}) {
  const c = { ...DEFAULT_DIAL_CONFIG, ...config };
  const { min, max } = scaleWindow;
  const { cx, cy, radius, sweep } = c;
  const ang = (/** @type {number} */ v) => angleForValue(v, min, max, sweep);

  const angleMin = ang(min);
  const angleMax = ang(max);
  const angleVal = ang(value);

  /** @type {DialTick[]} */
  const ticks = [];
  for (let v = min; v <= max; v += c.tickStep) {
    const major = v % c.majorStep === 0;
    const a = ang(v);
    const outer = polarPoint(cx, cy, c.tickOuterR, a);
    const inner = polarPoint(cx, cy, major ? c.majorInnerR : c.minorInnerR, a);
    let label = null;
    if (major) {
      const L = polarPoint(cx, cy, c.labelR, a);
      // 4px baseline nudge for optical centering
      label = { x: L.x, y: L.y + 4, text: String(v) };
    }
    ticks.push({ value: v, major, angle: a, outer, inner, label });
  }

  return {
    value,
    angle: angleVal,
    center: { x: cx, y: cy },
    radius,
    valuePoint: polarPoint(cx, cy, radius, angleVal),
    baselineArc: arcPath(cx, cy, radius, angleMin, angleMax),
    valueArc: arcPath(cx, cy, radius, angleMin, angleVal),
    ticks,
  };
}
