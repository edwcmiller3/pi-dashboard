// HUD geometry - the temperature scale window shared by the dial and the
// forecast plot. Pure, DOM-free. Math from computeScaleWindow() in
// design-mocks/instrument-hud.html.

/**
 * A closed temperature window [min, max] in °F, both snapped to `step`.
 * @typedef {object} ScaleWindow
 * @property {number} min lower edge, always a multiple of `step`
 * @property {number} max upper edge, always a multiple of `step`
 */

/** Default span of the window in °F. */
export const DEFAULT_SPAN = 40;
/** Default snap/grid step in °F. */
export const DEFAULT_STEP = 10;

/**
 * Scale window over the temperatures on screen. Data-driven because a fixed
 * window breaks in winter (arc sweeps backwards, negative percents). Snapping
 * down leaves headroom so lo/hi numerals stay off the track edges; a spread
 * wider than `span` widens the window rather than clipping.
 *
 * @param {number[]} temps every temperature the shared scale must cover
 *   (today's cur/high/low + each forecast day's lo/hi)
 * @param {number} [span=DEFAULT_SPAN] window width in °F
 * @param {number} [step=DEFAULT_STEP] snap/grid step in °F
 * @returns {ScaleWindow}
 */
export function computeScaleWindow(temps, span = DEFAULT_SPAN, step = DEFAULT_STEP) {
  const lo = Math.min(...temps);
  const hi = Math.max(...temps);
  let min = Math.floor(lo / step) * step; // snap down → headroom below
  if (min === lo) min -= step; // lo exactly on a gridline → one full step
  let max = min + span;
  if (hi >= max) {
    // span can't hold the data from this floor
    max = Math.ceil(hi / step) * step;
    if (max === hi) max += step; // hi exactly on a gridline → one full step
    min = Math.min(min, max - span); // keep covering lo; widen past span if needed
  }
  return { min, max };
}
