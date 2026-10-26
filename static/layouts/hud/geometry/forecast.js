// HUD geometry - forecast range plot: each day's lo/hi and the ruler numerals as
// left-edge percents on the shared scale. Pure, DOM-free. Math from the FORECAST
// RANGE BARS block in design-mocks/instrument-hud.html.

/** °F between ruler numerals. */
export const RULER_LABEL_STEP = 20;
/** °F between minor ruler ticks. */
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
 * Value as a percent of the window. computeScaleWindow's headroom keeps real
 * lo/hi strictly inside (0, 100), so no marker sits on a track edge.
 * @param {number} value
 * @param {import("./scale.js").ScaleWindow} scaleWindow
 * @returns {number}
 */
export function scalePct(value, scaleWindow) {
  return ((value - scaleWindow.min) / (scaleWindow.max - scaleWindow.min)) * 100;
}

/**
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
 * Number of minor ruler divisions for the tick gradient.
 * @param {import("./scale.js").ScaleWindow} scaleWindow
 * @returns {number}
 */
export function rulerDivisions(scaleWindow) {
  return (scaleWindow.max - scaleWindow.min) / RULER_TICK_STEP;
}
