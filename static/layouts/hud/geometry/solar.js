// HUD geometry - solar linear day-progress tape.
//
// Pure, DOM-free: maps sunrise/sunset/now (as minutes-of-day) to the daylight
// fraction, the "now" x position on the tape, and the marker/tick element
// specs. The renderer extracts minutes-of-day from the contract's ISO
// sunrise/sunset strings (via the core time helpers) before calling in.
//
// Ported math-identical from the SOLAR LINEAR TAPE IIFE in
// design-mocks/instrument-hud-d.html (lines 459-506). The mock's layout
// constants (tape endpoints xr/xs, baseline, idle ticks, sun-marker cross
// ticks) become SolarConfig with the mock values as defaults.

/**
 * @typedef {object} SolarPoint
 * @property {number} x
 * @property {number} y
 */

/**
 * @typedef {object} Segment
 * @property {number} x1
 * @property {number} y1
 * @property {number} x2
 * @property {number} y2
 */

/**
 * Tape layout constants (the mock's hardcoded numbers, viewBox 0 0 552 47).
 * @typedef {object} SolarConfig
 * @property {number} sunriseX left daylight bug / tape start (mock: 52)
 * @property {number} sunsetX right daylight bug / tape end (mock: 488)
 * @property {number} ty tape line y (mock: 20)
 * @property {number} baselineX1 dashed baseline start (mock: 8)
 * @property {number} baselineX2 dashed baseline end (mock: 544)
 * @property {number} idleTickStart first idle tick x (mock: 16)
 * @property {number} idleTickEnd last idle tick x, inclusive (mock: 540)
 * @property {number} idleTickStep idle tick spacing (mock: 24)
 * @property {number} idleTickLen idle tick length downward (mock: 4)
 * @property {number} bugHalf half-height of a sunrise/sunset bug (mock: 6)
 * @property {number} haloR sun-marker halo radius (mock: 6)
 * @property {number} ringR sun-marker ring radius (mock: 4)
 */

/** @type {SolarConfig} */
export const DEFAULT_SOLAR_CONFIG = {
  sunriseX: 52,
  sunsetX: 488,
  ty: 20,
  baselineX1: 8,
  baselineX2: 544,
  idleTickStart: 16,
  idleTickEnd: 540,
  idleTickStep: 24,
  idleTickLen: 4,
  bugHalf: 6,
  haloR: 6,
  ringR: 4,
};

// Sun-marker cross ticks: [dx1, dy1, dx2, dy2] offsets from the marker center
// (mock lines 491-494), the "~25% smaller than v1" set.
const CROSS_TICK_OFFSETS = [
  [0, -8, 0, -5.5],
  [0, 8, 0, 5.5],
  [-8, 0, -5.5, 0],
  [8, 0, 5.5, 0],
];

/**
 * @typedef {object} SolarGeometry
 * @property {number} fraction daylight fraction (now-sunrise)/(sunset-sunrise);
 *   RAW like the mock - NOT clamped, so it is <0 before sunrise and >1 after
 *   sunset (see module note)
 * @property {number} daylightMinutes sunset − sunrise, in minutes
 * @property {number} ty tape line y
 * @property {number} sunriseX
 * @property {number} sunsetX
 * @property {number} nowX x of the "now" sun marker along the tape
 * @property {{cx: number, cy: number, haloR: number, ringR: number, crossTicks: Segment[]}} sunMarker
 * @property {Segment[]} bugs sunrise + sunset vertical bugs
 * @property {Segment} baseline full-width dashed baseline
 * @property {Segment[]} idleTicks evenly spaced downward baseline ticks
 */

/**
 * Solar tape geometry for a moment in the day.
 *
 * Note: `fraction`/`nowX` are the mock's raw values and are intentionally NOT
 * clamped to the daylight span - at night (now before sunrise or after sunset)
 * `nowX` falls outside [sunriseX, sunsetX]. Night handling is out of scope for
 * the layout (plan: night mode not desired); the renderer can clamp or hide the
 * marker if desired. Flagged so the caller decides, rather than baking a policy.
 *
 * @param {object} t minutes-of-day (0-1439) for each moment
 * @param {number} t.sunriseMin
 * @param {number} t.sunsetMin
 * @param {number} t.nowMin
 * @param {Partial<SolarConfig>} [config]
 * @returns {SolarGeometry}
 */
export function solarGeometry({ sunriseMin, sunsetMin, nowMin }, config = {}) {
  const c = { ...DEFAULT_SOLAR_CONFIG, ...config };
  const { sunriseX, sunsetX, ty } = c;

  const daylightMinutes = sunsetMin - sunriseMin;
  const fraction = (nowMin - sunriseMin) / (sunsetMin - sunriseMin);
  const nowX = sunriseX + (sunsetX - sunriseX) * fraction;

  const crossTicks = CROSS_TICK_OFFSETS.map(([dx1, dy1, dx2, dy2]) => ({
    x1: nowX + dx1,
    y1: ty + dy1,
    x2: nowX + dx2,
    y2: ty + dy2,
  }));

  /** @type {Segment[]} */
  const bugs = [sunriseX, sunsetX].map((x) => ({
    x1: x,
    y1: ty - c.bugHalf,
    x2: x,
    y2: ty + c.bugHalf,
  }));

  /** @type {Segment[]} */
  const idleTicks = [];
  for (let x = c.idleTickStart; x <= c.idleTickEnd; x += c.idleTickStep) {
    idleTicks.push({ x1: x, y1: ty, x2: x, y2: ty + c.idleTickLen });
  }

  return {
    fraction,
    daylightMinutes,
    ty,
    sunriseX,
    sunsetX,
    nowX,
    sunMarker: { cx: nowX, cy: ty, haloR: c.haloR, ringR: c.ringR, crossTicks },
    bugs,
    baseline: { x1: c.baselineX1, y1: ty, x2: c.baselineX2, y2: ty },
    idleTicks,
  };
}
