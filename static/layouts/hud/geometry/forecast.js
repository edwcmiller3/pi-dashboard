// HUD geometry — forecast range plot.
//
// Pure, DOM-free: maps each forecast day's lo/hi onto the shared scale window
// as left-edge percents for the range-plot markers (hollow low ring · hairline
// connector · white-hot high dot), plus the ruler numeral positions. The
// renderer positions absolutely-placed HTML markers from these percents.
//
// Ported math-identical from the FORECAST RANGE BARS IIFE + the pct() helper
// in design-mocks/instrument-hud-d.html (pct line 510, ruler labels lines
// 522-531, per-day markers lines 533-545).

/** °F between ruler numerals (mock: labels every 20° from the floor). */
export const RULER_LABEL_STEP = 20;
/** °F between minor ruler ticks (mock: divisions = span / 5). */
export const RULER_TICK_STEP = 5;

/**
 * A day's lo/hi (subset of the ForecastDay contract the plot needs).
 * @typedef {object} RangeDay
 * @property {number} low_f
 * @property {number} high_f
 */

/**
 * Marker percents for one forecast day, on the shared scale.
 * @typedef {object} RangeMarker
 * @property {number} loPct left-edge % of the low ring
 * @property {number} hiPct left-edge % of the high dot
 * @property {number} linkLeftPct left-edge % of the connector (== loPct)
 * @property {number} linkWidthPct width % of the connector (hiPct − loPct)
 */

/**
 * A ruler numeral.
 * @typedef {object} RulerLabel
 * @property {number} value the °F
 * @property {number} pct left-edge % of the numeral
 */

/**
 * Position of a value on the scale, as a percent (mock pct()). 0% == min,
 * 100% == max. computeScaleWindow's headroom keeps real lo/hi strictly inside
 * (0, 100), so no marker sits on a track edge.
 * @param {number} value
 * @param {import("./scale.js").ScaleWindow} scaleWindow
 * @returns {number}
 */
export function scalePct(value, scaleWindow) {
  return ((value - scaleWindow.min) / (scaleWindow.max - scaleWindow.min)) * 100;
}

/**
 * Per-day range markers for the forecast plot.
 * @param {RangeDay[]} days
 * @param {import("./scale.js").ScaleWindow} scaleWindow shared scale window
 * @returns {RangeMarker[]}
 */
export function forecastRangePlot(days, scaleWindow) {
  return days.map((d) => {
    const loPct = scalePct(d.low_f, scaleWindow);
    const hiPct = scalePct(d.high_f, scaleWindow);
    return {
      loPct,
      hiPct,
      linkLeftPct: loPct,
      linkWidthPct: hiPct - loPct,
    };
  });
}

/**
 * Ruler numerals every `RULER_LABEL_STEP` °F from the window floor.
 * @param {import("./scale.js").ScaleWindow} scaleWindow
 * @returns {RulerLabel[]}
 */
export function forecastRuler(scaleWindow) {
  /** @type {RulerLabel[]} */
  const labels = [];
  for (let v = scaleWindow.min; v <= scaleWindow.max; v += RULER_LABEL_STEP) {
    labels.push({ value: v, pct: scalePct(v, scaleWindow) });
  }
  return labels;
}

/**
 * Number of minor ruler divisions for the tick gradient (mock: span / 5).
 * @param {import("./scale.js").ScaleWindow} scaleWindow
 * @returns {number}
 */
export function rulerDivisions(scaleWindow) {
  return (scaleWindow.max - scaleWindow.min) / RULER_TICK_STEP;
}
