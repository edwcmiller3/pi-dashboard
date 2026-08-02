"""Vendor the Meteocons static-SVG subset the meteocons packs render - DEV ONLY.

Re-runnable one-shot: pulls ONLY the icons the packs actually reference, at a
PINNED CDN version, into the repo so the running kiosk makes ZERO network calls
for icons (every SVG is served as a local static file via a relative url(...)).
Mirrors the weather-icons .woff2 subset discipline: a small, vendored, offline
asset set - never a runtime fetch.

    uv run python -m tools.vendor_meteocons

This module NEVER runs at import time and is NEVER called from the app runtime.
It exists purely to refresh the committed subset when the map or pin changes.
Run it by hand, review the diff, commit the SVGs.

What it writes (78 SVGs = 26 names x 3 styles), plus the upstream MIT license:

    static/packs/meteocons/svg/flat/<name>.svg
    static/packs/meteocons/svg/line/<name>.svg
    static/packs/meteocons/svg/mono/<name>.svg   (CDN style "monochrome")
    static/packs/meteocons/LICENSE-MIT.txt

The 26 names are the DISTINCT meteocons drawings the packs collapse the 27
semantic names onto (several IconTokens share a drawing); the semantic ->
meteocons name map itself lives in app/packs/meteocons.py, the single source of
truth the running app reads. This script only needs the distinct set to fetch.
"""

from __future__ import annotations

import sys
import urllib.error
import urllib.request
from pathlib import Path
from typing import Final

# Pinned CDN version - every fetched SVG comes from exactly this release, so the
# vendored subset is reproducible. Bump deliberately, then re-run and review.
PINNED_VERSION: Final = "3.0.0-next.10"

# CDN URL shape: .../<version>/svg-static/<style>/<name>.svg  (style is the
# UPSTREAM name; the local on-disk dir may differ - see _STYLES).
_CDN_TEMPLATE: Final = "https://cdn.meteocons.com/{version}/svg-static/{style}/{name}.svg"

# upstream CDN style -> local on-disk dir. "monochrome" is vendored as "mono"
# (the pack dir is meteocons-mono), the other two keep their names.
_STYLES: Final[dict[str, str]] = {
    "flat": "flat",
    "line": "line",
    "monochrome": "mono",
}

# The DISTINCT meteocons drawings the packs reference (21). Keep in sync with the
# right-hand side of app/packs/meteocons.py's map: this is exactly the set of
# values there, deduplicated. A test asserts every mapped name resolves to a
# vendored file, so drift here fails the suite rather than the kiosk.
_NAMES: Final[tuple[str, ...]] = (
    "clear-day",
    "clear-night",
    "mostly-clear-day",
    "mostly-clear-night",
    "partly-cloudy-day",
    "partly-cloudy-night",
    "overcast",
    "fog",
    "overcast-day-drizzle",
    "overcast-night-drizzle",
    "sleet",
    "overcast-day-rain",
    "overcast-night-rain",
    "overcast-day-snow",
    "overcast-night-snow",
    "partly-cloudy-day-rain",
    "partly-cloudy-night-rain",
    "partly-cloudy-day-snow",
    "partly-cloudy-night-snow",
    "thunderstorms",
    "not-available",
    "windsock",
    "humidity",
    "raindrop",
    "sunrise",
    "sunset",
)

# The upstream project's license (Meteocons by Bas Milius, MIT). Vendored beside
# the SVGs so the subset ships its attribution, mirroring the OFL.txt convention.
_LICENSE_URL: Final = "https://raw.githubusercontent.com/basmilius/weather-icons/master/LICENSE"

# Repo-relative destination root: static/packs/meteocons/ (svg/ + LICENSE).
_DEST_ROOT: Final = Path(__file__).resolve().parent.parent / "static" / "packs" / "meteocons"


# The CDN rejects the stdlib default UA (403); send an explicit one, as curl does.
_USER_AGENT: Final = "pi-dashboard-vendor-meteocons/1.0 (+dev-only one-shot)"


def _fetch(url: str) -> bytes:
    """GET a URL, returning its bytes. Raises on any non-200 / network error."""
    req = urllib.request.Request(url, headers={"User-Agent": _USER_AGENT})  # noqa: S310 - pinned https CDN, dev-only
    with urllib.request.urlopen(req) as resp:  # noqa: S310 - pinned https CDN, dev-only
        status = resp.status
        if status != 200:
            raise RuntimeError(f"{url} -> HTTP {status}")
        data: bytes = resp.read()
    return data


def _svg_url(style: str, name: str) -> str:
    return _CDN_TEMPLATE.format(version=PINNED_VERSION, style=style, name=name)


def main() -> int:
    """Fetch the pinned subset into the repo. Returns a process exit code.

    Stops (non-zero) on the FIRST failure rather than guessing a substitute, so a
    name that unexpectedly 404s is loud, not silently skipped.
    """
    svg_root = _DEST_ROOT / "svg"
    written = 0
    for cdn_style, local_dir in _STYLES.items():
        dest_dir = svg_root / local_dir
        dest_dir.mkdir(parents=True, exist_ok=True)
        for name in _NAMES:
            url = _svg_url(cdn_style, name)
            try:
                data = _fetch(url)
            except (urllib.error.HTTPError, urllib.error.URLError, RuntimeError) as exc:
                print(f"FAILED {url}: {exc}", file=sys.stderr)
                return 1
            (dest_dir / f"{name}.svg").write_bytes(data)
            written += 1
        print(f"{cdn_style:<11} -> svg/{local_dir}/  ({len(_NAMES)} files)")

    try:
        license_text = _fetch(_LICENSE_URL)
    except (urllib.error.HTTPError, urllib.error.URLError, RuntimeError) as exc:
        print(f"FAILED {_LICENSE_URL}: {exc}", file=sys.stderr)
        return 1
    (_DEST_ROOT / "LICENSE-MIT.txt").write_bytes(license_text)
    print(f"LICENSE-MIT.txt written ({len(license_text)} bytes)")

    print(f"vendored {written} SVGs from meteocons@{PINNED_VERSION}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
