// Shared admin panel DOM - the config editor, device health, and the transition
// overlay.
//
// The accepted mocks give every live skin identical panel markup (only the CSS
// differs), so it is built once here instead of copied into each skin. A skin
// owns its shell and stylesheet and drops these nodes into its containers.
// Render-only: taps call back into the controller through AdminCtx. Every class
// is `admin-`-prefixed (see layouts/classic/admin.js for why).
//
// Side-effect-free on import (the core graph's invariant, see core/machine.js).

import { el } from "./dom.js";

/** @typedef {import("./contract.js").AdminCtx} AdminCtx */
/** @typedef {import("./contract.js").AdminStats} AdminStats */
/** @typedef {import("./contract.js").ThrottleFlag} ThrottleFlag */
/** @typedef {import("./contract.js").ThrottleState} ThrottleState */
/** @typedef {import("./contract.js").Usage} Usage */
/** @typedef {import("./contract.js").AdminTransition} AdminTransition */
/** @typedef {import("./contract.js").ConfigKey} ConfigKey */
/** @typedef {import("./contract.js").ConfigKnob} ConfigKnob */
/** @typedef {import("./contract.js").ConfigView} ConfigView */

/** @type {readonly [ConfigKey, string][]} */
const KNOBS = [
  ["layout", "Layout"],
  ["theme", "Theme"],
  ["icon_pack", "Icon pack"],
];

/** THEME "" is the built-in palette. @param {string} value */
const label = (value) => value || "default";

/** @param {string} text @param {string} className @returns {HTMLElement} */
function button(text, className) {
  const b = el("button", className, text);
  b.setAttribute("type", "button");
  return b;
}

/**
 * @param {ConfigKey} key @param {string} name @param {ConfigKnob} knob
 * @param {ConfigView} view @param {AdminCtx} ctx
 */
function knobRow(key, name, knob, view, ctx) {
  const pick = view.staged[key];
  const live = el("span", "admin-knob-live", "Live: ");
  live.append(el("b", null, label(knob.current)));
  const top = el("div", "admin-knob-top");
  top.append(el("span", "admin-knob-name", name), live);

  const opts = el("div", "admin-opts");
  for (const value of knob.options) {
    const opt = /** @type {HTMLButtonElement} */ (button(label(value), "admin-opt"));
    if (value === knob.current) opt.classList.add(pick === undefined ? "admin-current" : "admin-was-current");
    if (value === pick) opt.classList.add("admin-staged");
    opt.setAttribute("aria-pressed", String(value === (pick ?? knob.current)));
    opt.disabled = view.busy;
    opt.addEventListener("click", () => ctx.stage(key, value));
    opts.append(opt);
  }

  const row = el("div", "admin-knob");
  row.append(top, opts);
  return row;
}

/** @param {ConfigView} view @returns {string} */
function summary(view) {
  if (view.busy) return "Applying…";
  if (view.notice) return view.notice.text;
  if (view.pending) return `${view.pending} change${view.pending === 1 ? "" : "s"} staged`;
  return "No changes staged";
}

/** @param {ConfigView} view @param {AdminCtx} ctx */
function applyBar(view, ctx) {
  const text = el("span", "admin-apply-summary", summary(view));
  if (view.notice?.kind === "error") text.classList.add("admin-is-error");
  else if (view.pending || view.busy) text.classList.add("admin-has-staged");

  const on = view.pending > 0 && !view.busy;
  const btn = /** @type {HTMLButtonElement} */ (button("Apply", on ? "admin-apply-btn admin-on" : "admin-apply-btn admin-off"));
  btn.disabled = !on;
  btn.addEventListener("click", () => ctx.apply());

  const bar = el("div", "admin-apply-bar");
  bar.append(text, btn);
  return bar;
}

/**
 * The #admin-config panel body: one row per knob (selection only, no free
 * text) and the Apply bar.
 * @param {ConfigView} view @param {AdminCtx} ctx @returns {HTMLElement[]}
 */
export function configPanel(view, ctx) {
  const { config } = view;
  if (!config) return [el("p", "admin-empty", view.notice?.text ?? "Loading…")];
  return [...KNOBS.map(([key, name]) => knobRow(key, name, config[key], view, ctx)), applyBar(view, ctx)];
}

// ── device health ────────────────────────────────────────────────────────────

// Tile glyphs from the mocks (trusted own markup). Rounded rects here; a skin
// that wants square corners overrides `rx` in CSS.
const GLYPH = {
  cpu: '<svg viewBox="0 0 24 24" aria-hidden="true"><rect x="5" y="5" width="14" height="14" rx="2"/><rect x="9" y="9" width="6" height="6"/><path d="M9 2v2M15 2v2M9 20v2M15 20v2M2 9h2M2 15h2M20 9h2M20 15h2"/></svg>',
  ram: '<svg viewBox="0 0 24 24" aria-hidden="true"><rect x="3" y="8" width="18" height="9" rx="1.5"/><path d="M7 17v3M12 17v3M17 17v3"/></svg>',
  temp: '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M14 14.8V4a2 2 0 0 0-4 0v10.8a4 4 0 1 0 4 0z"/></svg>',
  disk: '<svg viewBox="0 0 24 24" aria-hidden="true"><rect x="3" y="4" width="18" height="16" rx="2"/><path d="M7 20V9h10v11M10 13h.01"/></svg>',
  uptime: '<svg viewBox="0 0 24 24" aria-hidden="true"><circle cx="12" cy="12" r="9"/><path d="M12 7v5l3 2"/></svg>',
  host: '<svg viewBox="0 0 24 24" aria-hidden="true"><rect x="4" y="4" width="16" height="16" rx="2"/><path d="M9 9h6v6H9z"/></svg>',
  throttle: '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M13 2 4 14h7l-1 8 9-12h-7l1-8z"/></svg>',
  network:
    '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M2 9a16 16 0 0 1 20 0M5 13a10 10 0 0 1 14 0M8.5 16.5a5 5 0 0 1 7 0"/><circle cx="12" cy="20" r="0.6"/></svg>',
};

/** Typed by contract.js ThrottleFlag, so a missing label fails tsc. @type {Record<ThrottleFlag, string>} */
const THROTTLE_LABEL = {
  "under-voltage": "Under-voltage",
  "arm-frequency-capped": "Freq capped",
  throttled: "Throttled",
  "soft-temp-limit": "Soft temp limit",
};

/** @param {ThrottleState} s */
const when = (s) => (s.now && s.occurred ? "now & earlier" : s.now ? "now" : "earlier");

// The value (not the tile) turns amber/red per skin at or above these, as in the
// mocks' degraded frame. Temp: the Pi 5 firmware starts throttling the ARM cores
// at 80 °C.
const WARN_PCT = 90;
const WARN_TEMP_C = 80;

const GIB = 2 ** 30;
/** GB as the mocks write it: "4.1 / 29 GB" - one decimal, totals ≥10 whole. @param {Usage} u @returns {[string, string]} */
function gb(u) {
  const total = u.total / GIB;
  return [(u.used / GIB).toFixed(1), ` / ${total.toFixed(total < 10 ? 1 : 0)} GB`];
}

/** @param {Usage} u */
const pct = (u) => (u.total > 0 ? (100 * u.used) / u.total : 0);

/** @param {number} s */
function uptime(s) {
  const d = Math.floor(s / 86400);
  const h = Math.floor((s % 86400) / 3600);
  const m = Math.floor((s % 3600) / 60);
  if (d) return `${d}d ${h}h`;
  return h ? `${h}h ${m}m` : `${m}m`;
}

/**
 * One tile. `value` null renders "unavailable"; a [main, small] pair renders the
 * unit/qualifier small, as the mocks do.
 * @param {string} glyph @param {string} name
 * @param {string | [string, string] | Node[] | null} value
 * @param {{ warn?: boolean, wide?: boolean, kind?: string }} [opts]
 */
function metric(glyph, name, value, { warn = false, wide = false, kind } = {}) {
  const m = el("div", "admin-metric");
  if (wide) m.classList.add("admin-metric-wide");
  if (kind) m.classList.add(`admin-metric-${kind}`);
  if (warn) m.classList.add("admin-is-warn");
  const k = el("div", "admin-k");
  k.innerHTML = glyph; // trusted own SVG only
  k.append(name);
  m.append(k);

  if (value === null) {
    m.classList.add("admin-unavail");
    m.append(el("div", "admin-v", "unavailable"));
  } else if (typeof value === "string") {
    m.append(el("div", "admin-v", value));
  } else if (typeof value[0] === "string") {
    const v = el("div", "admin-v", /** @type {string} */ (value[0]));
    v.append(el("small", null, /** @type {string} */ (value[1])));
    m.append(v);
  } else {
    const flags = el("div", "admin-flags");
    flags.append(.../** @type {Node[]} */ (value));
    m.append(flags);
  }
  return m;
}

/** Named flags, never raw hex alone; the hex rides along for SSH cross-checks. @param {AdminStats["throttle"]} t */
function throttleFlags(t) {
  if (!t) return null;
  const hex = el("span", "admin-hex", t.raw);
  if (!t.flags.length) return [el("span", "admin-flag admin-ok", "No throttling"), hex];
  const quals = new Set(t.flags.map(when));
  // One shared qualifier when every flag agrees (the mock's case), else per flag.
  const pills = t.flags.map((f) =>
    el("span", "admin-flag admin-bad", quals.size === 1 ? THROTTLE_LABEL[f.flag] : `${THROTTLE_LABEL[f.flag]} · ${when(f)}`),
  );
  const shared = quals.size === 1 ? [el("span", "admin-flag admin-muted", [...quals][0])] : [];
  return [...pills, ...shared, hex];
}

/** @param {AdminStats["network"]} n @returns {[string, string] | null} */
function network(n) {
  if (!n) return null;
  return [n.ip, `${n.prefix === null ? "" : ` /${n.prefix}`} · ${n.iface}`];
}

/**
 * The #admin-health panel body: eight tiles, each "unavailable" on its own when
 * its probe is (off-Pi: temp + throttle). null = the poll itself failed.
 * @param {AdminStats | null} stats @returns {HTMLElement[]}
 */
export function healthPanel(stats) {
  if (!stats) return [el("p", "admin-empty", "Device health unavailable")];
  const { cpu_percent: cpu, memory, disk, uptime_s, host, temp_c, throttle } = stats;
  const grid = el("div", "admin-metrics");
  grid.append(
    metric(GLYPH.cpu, "CPU", cpu === null ? null : `${Math.round(cpu)}%`, { warn: cpu !== null && cpu >= WARN_PCT }),
    metric(GLYPH.ram, "RAM", memory && gb(memory), { warn: !!memory && pct(memory) >= WARN_PCT }),
    metric(GLYPH.temp, "Temp", temp_c === null ? null : [temp_c.toFixed(1), " °C"], {
      warn: temp_c !== null && temp_c >= WARN_TEMP_C,
    }),
    metric(GLYPH.disk, "Disk", disk && gb(disk), { warn: !!disk && pct(disk) >= WARN_PCT }),
    metric(GLYPH.uptime, "Uptime", uptime_s === null ? null : uptime(uptime_s)),
    metric(GLYPH.host, "Host", host, { kind: "host" }),
    metric(GLYPH.throttle, "Throttle", throttleFlags(throttle), { wide: true }),
    metric(GLYPH.network, "Network", network(stats.network), { wide: true, kind: "net" }),
  );
  return [grid];
}

/** @type {Record<Exclude<AdminTransition, "error">, [string, string]>} */
const COPY = {
  applying: ["Restarting dashboard…", "The display will reload when it's back."],
  rebooting: ["Rebooting…", "The screen will go dark, then return to the dashboard."],
};

/**
 * The full-screen overlay a skin paints over its panels, or null to clear it.
 * @param {AdminTransition | null} state @param {string | undefined} message
 * @param {AdminCtx} ctx @returns {HTMLElement | null}
 */
export function transitionScrim(state, message, ctx) {
  if (!state) return null;
  const term = el("div", "admin-terminal");
  if (state === "error") {
    term.classList.add("admin-is-error");
    const back = button("Back to admin", "admin-dbtn admin-ghost");
    back.addEventListener("click", () => ctx.dismiss());
    term.append(el("div", "admin-big", "Restart didn't finish"), el("div", "admin-small", message ?? ""), back);
  } else {
    const spin = el("div", "admin-spin");
    spin.setAttribute("aria-hidden", "true");
    const [big, small] = COPY[state];
    term.append(spin, el("div", "admin-big", big), el("div", "admin-small", small));
  }
  const scrim = el("div", "admin-scrim");
  scrim.setAttribute("role", "status");
  scrim.append(term);
  return scrim;
}
