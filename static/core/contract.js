// Types only (no runtime exports): JSDoc mirrors of app/contract.py so tsc checks
// how the frontend consumes the API. Keep in sync with app/contract.py.

/** @typedef {"personal" | "holiday" | "observance" | "info"} Kind */

/**
 * Day/night-resolved condition slug (mirrors app/weather_codes.py IconToken).
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
 * Chrome glyphs a layout requests directly; never part of /api/data.
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
 * The hooks a layout module's exported `layout` implements for core/machine.js.
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

// ── admin skin ───────────────────────────────────────────────────────────────
// Admin is not data-driven by /api/data, so it gets its own thin contract rather
// than stretching Layout.

/** @typedef {"layout" | "theme" | "icon_pack"} ConfigKey */

/**
 * One knob from GET /api/admin/config (mirrors app/main.py ConfigKnob). A THEME
 * of "" is the built-in palette.
 * @typedef {object} ConfigKnob
 * @property {string} current the value actually rendering
 * @property {string[]} options every selectable value
 */

/** @typedef {Record<ConfigKey, ConfigKnob>} AdminConfig GET /api/admin/config */

/**
 * The config panel's render input, derived by the controller.
 * @typedef {object} ConfigView
 * @property {AdminConfig | null} config null while loading or when unavailable
 * @property {Partial<Record<ConfigKey, string>>} staged pending values, only
 *   those differing from current
 * @property {number} pending count of staged changes
 * @property {boolean} busy an apply is in flight; the panel is inert
 * @property {{ kind: "info" | "error", text: string } | null} notice
 */

// GET /api/admin/stats (mirrors app/stats.py). Every field is null when its
// probe is unavailable - temp/throttle always are off-Pi.

/**
 * Must match app/stats.py ThrottleFlag; tests/test_stats.py diffs the two.
 * @typedef {"under-voltage" | "arm-frequency-capped" | "throttled" | "soft-temp-limit"} ThrottleFlag
 */

/**
 * @typedef {object} ThrottleState
 * @property {ThrottleFlag} flag
 * @property {boolean} now set right now
 * @property {boolean} occurred set at some point since boot (sticky)
 */

/**
 * @typedef {object} Throttle
 * @property {string} raw the get_throttled hex, e.g. "0x50005"
 * @property {ThrottleState[]} flags only the set flags; empty = healthy
 */

/** @typedef {{ used: number, total: number }} Usage bytes */

/**
 * @typedef {object} NetworkInfo
 * @property {string} iface
 * @property {string} ip
 * @property {string | null} netmask
 * @property {number | null} prefix
 */

/**
 * @typedef {object} AdminStats
 * @property {number | null} cpu_percent
 * @property {Usage | null} memory
 * @property {Usage | null} disk
 * @property {number | null} uptime_s
 * @property {string | null} host
 * @property {number | null} temp_c
 * @property {Throttle | null} throttle
 * @property {NetworkInfo | null} network
 */

/** @typedef {"restart" | "reboot"} AdminAction a device action */

/**
 * The device actions panel's render input, derived by the controller.
 * @typedef {object} ActionsView
 * @property {boolean | null} reboot whether Reboot can work (polkit grants it);
 *   null while still asking
 * @property {AdminAction | null} confirming the action awaiting its explicit
 *   confirm; the skin shows the confirm dialog while set
 * @property {boolean} busy an action is in flight; the panel is inert
 * @property {string | null} error why the last action didn't go through
 */

/**
 * What the controller hands a skin at mount.
 * @typedef {object} AdminCtx
 * @property {() => void} back return to the dashboard; the skin wires its back
 *   arrow to this
 * @property {(key: ConfigKey, value: string) => void} stage select a knob value
 *   (re-selecting the current value un-stages it)
 * @property {() => void} apply apply the staged values
 * @property {() => void} dismiss clear an error transition, back to the panels
 * @property {(action: AdminAction) => void} request first tap: ask to confirm
 *   `action` (nothing fires yet)
 * @property {() => void} confirm second tap: fire the action being confirmed
 * @property {() => void} cancel drop the pending confirm
 */

/**
 * The full-screen transitional states a skin paints over its panels; null clears.
 * @typedef {"applying" | "rebooting" | "error"} AdminTransition
 */

/**
 * The render-only hooks a layout's admin skin (layouts/<slug>/admin.js) exports
 * as `admin`; all behavior lives in core/admin.js.
 * @typedef {object} AdminSkin
 * @property {(root: HTMLElement, ctx: AdminCtx) => void} mount builds the shell -
 *   header with back arrow + the #admin-config / #admin-health / #admin-actions
 *   panel containers
 * @property {(view: ConfigView) => void} renderConfig
 * @property {(stats: AdminStats | null) => void} renderStats null = the poll
 *   failed (the whole panel is unavailable)
 * @property {(view: ActionsView) => void} renderActions the #admin-actions
 *   panel and, while `view.confirming` is set, its confirm dialog
 * @property {(state: AdminTransition | null, message?: string) => void} renderTransition
 */

export {};
