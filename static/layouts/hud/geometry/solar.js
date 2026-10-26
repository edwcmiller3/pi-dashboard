// HUD geometry - solar day-progress tape: sunrise/sunset/now (minutes-of-day) to
// tape positions and marker specs. Pure, DOM-free. Math and SolarConfig defaults
// from the SOLAR LINEAR TAPE block in design-mocks/instrument-hud.html.

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
 * Tape layout constants, in the viewBox 0 0 552 47.
 * @typedef {object} SolarConfig
 * @property {number} sunriseX left daylight bug / tape start
 * @property {number} sunsetX right daylight bug / tape end
 * @property {number} ty tape line y
 * @property {number} baselineX1 dashed baseline start
 * @property {number} baselineX2 dashed baseline end
 * @property {number} idleTickStart first idle tick x
 * @property {number} idleTickEnd last idle tick x, inclusive
 * @property {number} idleTickStep idle tick spacing
 * @property {number} idleTickLen idle tick length downward
 * @property {number} bugHalf half-height of a sunrise/sunset bug
 * @property {number} haloR sun-marker halo radius
 * @property {number} ringR sun-marker ring radius
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

// Sun-marker cross ticks: [dx1, dy1, dx2, dy2] offsets from the marker center.
const CROSS_TICK_OFFSETS = [
  [0, -8, 0, -5.5],
  [0, 8, 0, 5.5],
  [-8, 0, -5.5, 0],
  [8, 0, 5.5, 0],
];

/**
 * @typedef {object} SolarGeometry
 * @property {number} fraction daylight fraction; unclamped (<0 before sunrise,
 *   >1 after sunset)
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
 * Tape geometry for a moment in the day. `fraction`/`nowX` are deliberately
 * unclamped - at night `nowX` falls off the tape and the renderer decides.
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
