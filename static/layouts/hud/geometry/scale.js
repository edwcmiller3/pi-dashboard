// HUD geometry - shared temperature scale window.
//
// Pure, DOM-free. This is the single scale both the 240° temp dial and the
// forecast range plot render against, so it lives on its own and both import it.
//
// Ported verbatim (math-identical) from computeScaleWindow() in
// design-mocks/instrument-hud-d.html (script IIFE, lines 361-374) and
// cross-checked against design-mocks/instrument-hud-d-winter.html (lines
// 366-391, which drives the SCALE 10–50 winter window).

/**
 * A closed temperature window [min, max] in °F, both snapped to `step`.
 * @typedef {object} ScaleWindow
 * @property {number} min lower edge, always a multiple of `step`
 * @property {number} max upper edge, always a multiple of `step`
 */

/** Default span of the window in °F (narrowed from 60 → 40 on 2026-07-25). */
export const DEFAULT_SPAN = 40;
/** Default snap/grid step in °F. */
export const DEFAULT_STEP = 10;

/**
 * Derive the scale window from the temperatures currently on screen.
 *
 * A hardcoded window (the mock's original MIN=50/MAX=110) breaks in winter:
 * below the floor the dial's arc sweeps the wrong way and the range plot
 * computes negative percents. Instead the floor is `min(all temps)` snapped
 * DOWN to a multiple of `step` - the snap itself provides 0–9 °F of headroom
 * (the "gutter" that keeps the flanking lo/hi numerals off the track edges);
 * if the coldest reading lands exactly on a gridline we drop one more full
 * step so it never touches the edge. If a freak spread exceeds `span`, the
 * window widens in whole steps rather than clipping data.
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
