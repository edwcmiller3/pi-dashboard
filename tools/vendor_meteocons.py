"""Dev-only: vendor the Meteocons SVG subset the packs reference, at a pinned
CDN version, so the kiosk makes no network calls for icons.

    uv run python -m tools.vendor_meteocons

Run by hand when the map or pin changes, review the diff, commit. Writes:

    static/packs/meteocons/svg/{flat,line,mono}/<name>.svg
    static/packs/meteocons/LICENSE-MIT.txt
"""

from __future__ import annotations

import sys
import urllib.error
import urllib.request
from pathlib import Path
from typing import Final

# Bump deliberately, then re-run and review.
PINNED_VERSION: Final = "3.0.0-next.10"

# `style` is the upstream name; see _STYLES for the local dir.
_CDN_TEMPLATE: Final = "https://cdn.meteocons.com/{version}/svg-static/{style}/{name}.svg"

# upstream CDN style -> local dir.
_STYLES: Final[dict[str, str]] = {
    "flat": "flat",
    "line": "line",
    "monochrome": "mono",
}

# Must equal the distinct values of app/packs/meteocons.py's map. A test asserts
# every mapped name resolves to a vendored file.
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

# Meteocons by Bas Milius, MIT; vendored beside the SVGs for attribution.
_LICENSE_URL: Final = "https://raw.githubusercontent.com/basmilius/weather-icons/master/LICENSE"

_DEST_ROOT: Final = Path(__file__).resolve().parent.parent / "static" / "packs" / "meteocons"


# The CDN rejects the stdlib default UA (403); send an explicit one, as curl does.
_USER_AGENT: Final = "pi-dashboard-vendor-meteocons/1.0 (+dev-only one-shot)"


def _fetch(url: str) -> bytes:
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
    """Stops on the first failure, so an unexpected 404 is loud, not skipped."""
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
