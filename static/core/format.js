// Pure, DOM-free presentation formatters.

/** @typedef {import("./contract.js").WeatherBlock} WeatherBlock */
/** @typedef {import("./contract.js").CalendarBlock} CalendarBlock */

// "Updated" = the OLDEST fetched_at among OK sources, so it never over-claims
// freshness. Compared by instant so mixed UTC offsets order correctly.
/**
 * @param {(WeatherBlock | CalendarBlock | null | undefined)[]} sources
 * @returns {string | null}
 */
export function pickUpdated(sources) {
  // Drop unparseable stamps: every `<` against NaN is false, so a garbage stamp
  // seen first would win the min. flatMap narrows `fetched_at` to string.
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

// Glyph and value are separate so the glyph can be styled independently.
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
