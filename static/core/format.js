// Core presentation formatters — pure, DOM-free.
//
// Weather H/L pairs and the status "Updated" pick. Neither touches the DOM; both
// return plain data a layout turns into markup.

/** @typedef {import("./contract.js").WeatherBlock} WeatherBlock */
/** @typedef {import("./contract.js").CalendarBlock} CalendarBlock */

// "Updated" = the OLDEST fetched_at among sources that fetched OK — so the
// stamp honestly means "every fresh source is at least this current," never
// over-claiming by showing the most-recent one. Compared by instant (epoch) so
// mixed UTC offsets order correctly. Returns the chosen ISO string, or null
// when nothing fetched OK.
/**
 * @param {(WeatherBlock | CalendarBlock | null | undefined)[]} sources
 * @returns {string | null}
 */
export function pickUpdated(sources) {
  // Drop unparseable stamps up front: Date.parse(bad) is NaN, and every `<`
  // comparison with NaN is false, so a garbage stamp encountered first would
  // "win" the min and never be beaten — over-claiming freshness. Filtering
  // makes the pick correct regardless of input order. (flatMap, not
  // filter+map — it narrows `fetched_at` to string in one pass.)
  const stamps = sources.flatMap((s) =>
    s && s.ok && s.fetched_at && !Number.isNaN(Date.parse(s.fetched_at))
      ? [s.fetched_at]
      : [],
  );
  return stamps.reduce(
    (best, iso) => (best === null || Date.parse(iso) < Date.parse(best) ? iso : best),
    /** @type {string | null} */ (null),
  );
}

/**
 * One glyph+value line of a stacked H/L pair.
 * @typedef {{ glyph: string, temp: string }} HiLoLine
 */

// The hero's H/L pair, stacked beside the big temp (▴ over ▾) instead of
// trailing the condition text — a long description no longer stretches the
// left cluster. Glyph and value are separate so the glyph can be styled
// (size/color) independently.
/**
 * @param {{ high_f: number, low_f: number }} c
 * @returns {{ hi: HiLoLine, lo: HiLoLine }}
 */
export function fmtHiLo({ high_f, low_f }) {
  return {
    hi: { glyph: "▴", temp: `${high_f}°` },
    lo: { glyph: "▾", temp: `${low_f}°` },
  };
}
