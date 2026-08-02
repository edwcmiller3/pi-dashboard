// Core contract typedefs - the layout-agnostic type surface.
//
// JSDoc @typedefs mirroring app/contract.py so an editor and `tsc --checkJs`
// verify the contract the backend produces is consumed correctly across the
// core + layout module graph. Keep in sync with app/contract.py. This module is
// types only: no runtime exports (referenced via `import("./contract.js").TypeName`
// in JSDoc), so it trivially satisfies the core graph's import-safety invariant.

/** @typedef {"personal" | "holiday" | "observance" | "info"} Kind */

/**
 * A semantic, day/night-resolved weather condition slug (mirrors
 * app/weather_codes.py IconToken). An icon pack maps each to a concrete glyph;
 * the token preserves the condition distinction even where a pack collapses it.
 * @typedef {(
 *   "clear-day" | "clear-night" | "mostly-clear-day" | "mostly-clear-night" |
 *   "partly-cloudy-day" | "partly-cloudy-night" | "overcast" | "fog" |
 *   "drizzle-day" | "drizzle-night" | "freezing-drizzle" | "rain-day" |
 *   "rain-night" | "freezing-rain" | "snow-day" | "snow-night" |
 *   "showers-day" | "showers-night" | "snow-showers-day" | "snow-showers-night" |
 *   "thunderstorm" | "not-available"
 * )} IconToken
 */

/**
 * The fixed chrome-glyph names a layout requests directly (wind, humidity,
 * precip, sunrise, sunset). Not contract types: these never flow through
 * /api/data - they are the frontend's own UI/stat glyph vocabulary.
 * @typedef {"wind" | "humidity" | "precip" | "sunrise" | "sunset"} GlyphName
 */

/**
 * @typedef {object} IconPack
 * @property {(name: IconToken | GlyphName, extra?: string) => HTMLElement} renderIcon
 */

/**
 * @typedef {object} AgendaItem
 * @property {string} start ISO datetime-with-offset (timed) or "YYYY-MM-DD" (all-day)
 * @property {string} [end] exclusive upper bound; absent on single-day/instant items
 * @property {boolean} all_day
 * @property {string} title untrusted PII - render via textContent only
 * @property {Kind} kind
 */

/**
 * @typedef {object} CurrentWeather
 * @property {number} temp_f
 * @property {number} feels_like_f
 * @property {number} code
 * @property {string} text human label
 * @property {IconToken} icon an IconToken condition slug
 * @property {boolean} is_day
 * @property {number} humidity_pct
 * @property {number} wind_mph
 * @property {number} precip_prob_pct
 * @property {number} high_f
 * @property {number} low_f
 * @property {string} sunrise ISO datetime-with-offset
 * @property {string} sunset ISO datetime-with-offset
 */

/**
 * @typedef {object} ForecastDay
 * @property {string} date
 * @property {number} code
 * @property {string} text
 * @property {IconToken} icon an IconToken condition slug
 * @property {number} high_f
 * @property {number} low_f
 * @property {number} precip_prob_pct
 * @property {boolean} [precip_expected] backend is_wet(code) gate; absent (a
 *   pre-field cached block) reads as dry, so the precip line stays hidden
 */

/**
 * @typedef {object} WeatherBlock
 * @property {boolean} ok
 * @property {string | null} fetched_at
 * @property {number} [ttl]
 * @property {string} [attempted_at]
 * @property {CurrentWeather} current
 * @property {ForecastDay[]} forecast
 */

/**
 * @typedef {object} CalendarBlock
 * @property {boolean} ok
 * @property {string | null} fetched_at
 * @property {number} [ttl]
 * @property {string} [attempted_at]
 * @property {AgendaItem[]} events
 */

/**
 * @typedef {object} DashboardDoc
 * @property {string} generated_at
 * @property {boolean} clock_synced
 * @property {WeatherBlock} weather
 * @property {CalendarBlock} calendar
 */

/**
 * Options the core passes to a layout's renderStatus hook.
 * @typedef {object} StatusOpts
 * @property {boolean} [stale] force an all-stale, dashed "Updated" row (fetch failed)
 * @property {() => Promise<void>} [refresh] the core's manual-refresh primitive
 *   (POST /refresh + reload); the layout wires its refresh control to this
 */

/**
 * The layout interface the core state machine drives. A layout is an ES module
 * exporting a `layout` object implementing these seven hooks: the core owns
 * WHEN to render; the layout owns WHAT renders and all of its own DOM/CSS.
 * @typedef {object} Layout
 * @property {(root: HTMLElement, ctx: { icon: IconPack }) => void} mount builds
 *   the layout's DOM shell; `ctx.icon` injects the active icon pack
 * @property {(now: Date, synced: boolean) => void} renderClock `synced` true =
 *   clock trustworthy (hide any warning); false = Pi clock not NTP-synced
 * @property {(weather: WeatherBlock) => void} renderCurrent
 * @property {(days: ForecastDay[]) => void} renderForecast
 * @property {(events: AgendaItem[], calendarOk: boolean, clockSynced: boolean) => void} renderAgenda
 * @property {(doc: DashboardDoc | null, opts: StatusOpts) => void} renderStatus
 * @property {() => void} renderUnavailable
 */

export {};
