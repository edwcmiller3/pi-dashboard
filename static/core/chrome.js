// Inline SVG for UI controls (admin cog, back arrow), kept out of the icon packs.
// Trusted markup for innerHTML - never interpolate a contract/user string in.
//
// Paths from Lucide (lucide.dev) `settings` + `arrow-left` - ISC License, with
// Feather-derived portions MIT (Copyright (c) Cole Bemis).

const SVG_OPEN =
  '<svg viewBox="0 0 24 24" aria-hidden="true" fill="none" stroke="currentColor" ' +
  'stroke-width="2" stroke-linecap="round" stroke-linejoin="round">';

export const SETTINGS_SVG =
  SVG_OPEN +
  '<path d="M12.22 2h-.44a2 2 0 0 0-2 2v.18a2 2 0 0 1-1 1.73l-.43.25a2 2 0 0 1-2 0l-.15-.08a2 2 0 0 0-2.73.73l-.22.38a2 2 0 0 0 .73 2.73l.15.1a2 2 0 0 1 1 1.72v.51a2 2 0 0 1-1 1.74l-.15.09a2 2 0 0 0-.73 2.73l.22.38a2 2 0 0 0 2.73.73l.15-.08a2 2 0 0 1 2 0l.43.25a2 2 0 0 1 1 1.73V20a2 2 0 0 0 2 2h.44a2 2 0 0 0 2-2v-.18a2 2 0 0 1 1-1.73l.43-.25a2 2 0 0 1 2 0l.15.08a2 2 0 0 0 2.73-.73l.22-.39a2 2 0 0 0-.73-2.73l-.15-.08a2 2 0 0 1-1-1.74v-.5a2 2 0 0 1 1-1.74l.15-.09a2 2 0 0 0 .73-2.73l-.22-.38a2 2 0 0 0-2.73-.73l-.15.08a2 2 0 0 1-2 0l-.43-.25a2 2 0 0 1-1-1.73V4a2 2 0 0 0-2-2z"/>' +
  '<circle cx="12" cy="12" r="3"/></svg>';

export const BACK_SVG = SVG_OPEN + '<path d="m12 19-7-7 7-7"/><path d="M19 12H5"/></svg>';
