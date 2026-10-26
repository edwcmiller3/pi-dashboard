"""Render the README mockup screenshot from fabricated, PII-free data.

Runs the real app locally against an injected fixture cache and captures it
with headless Chrome into docs/mockup.png:

    uv run python -m tools.mockup

Every stamp in the fixture is fresh, so the server's boot tick serves it
verbatim - no live fetch and no .env needed.

The page's clock and today-awareness (next-up, roll-off) follow the browser's
local time, so Chrome runs under a fixed-offset TZ chosen so it reads 2 PM, with
the fixture's events in that same zone. `--serve` instead builds the fixture in
the machine's local zone, so which states show depends on the time of day.

The frame aims to exercise every marquee state that can coexist: wet and dry
forecast cards, an observance pill, a multi-day all-day span, "+N earlier"
roll-off, the next-up highlight, the "+N more" trim and the "+N more days"
footer. Mutually exclusive states (quiet day, stale dots, clock warning, cold
boot, a partially rolled day) can't share it.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone, tzinfo
from pathlib import Path
from zoneinfo import ZoneInfo

from app.contract import AgendaItem, CurrentWeather, DashboardDoc, ForecastDay, Kind
from app.weather_codes import describe, is_wet

REPO: Path = Path(__file__).resolve().parent.parent
OUT: Path = REPO / "docs" / "mockup.png"
PORT: int = 8141
DISPLAY_HOUR: int = 14  # the hour the mockup clock reads, whenever it's run
CHROME: str = os.environ.get(
    "CHROME_BIN", "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
)


def fake_zone() -> tuple[str, timezone]:
    """A fixed-offset zone where the current hour is DISPLAY_HOUR, as (name for
    Chrome's TZ, Python timezone). Etc/GMT names invert the sign (Etc/GMT+4 is
    UTC-4)."""
    offset = (DISPLAY_HOUR - datetime.now(timezone.utc).hour) % 24
    if offset > 12:
        offset -= 24  # keep within the Etc/GMT-12..+11 range
    name = "Etc/GMT" if offset == 0 else f"Etc/GMT{-offset:+d}"
    return name, timezone(timedelta(hours=offset))


def build_doc(tz: tzinfo) -> DashboardDoc:
    now = datetime.now(tz)

    def day(n: int) -> str:
        return (now + timedelta(days=n)).strftime("%Y-%m-%d")

    def iso(dt: datetime) -> str:
        return dt.isoformat(timespec="seconds")

    def timed(
        title: str, hh: int, mm: int, dur_min: int, plus_days: int = 0
    ) -> AgendaItem:
        start = now.replace(hour=hh, minute=mm, second=0, microsecond=0) + timedelta(
            days=plus_days
        )
        return {
            "start": iso(start),
            "end": iso(start + timedelta(minutes=dur_min)),
            "all_day": False,
            "title": title,
            "kind": "personal",
        }

    def all_day(title: str, on: int) -> AgendaItem:
        # One per-day item of a multi-day span, as `normalize_events` emits them.
        return {
            "start": day(on),
            "end": day(on + 1),
            "all_day": True,
            "title": title,
            "kind": "personal",
        }

    def pill(title: str, on: int, kind: Kind = "holiday") -> AgendaItem:
        return {"start": day(on), "all_day": True, "title": title, "kind": kind}

    events: list[AgendaItem] = [
        # Today - enough morning events that the fit pass rolls the oldest off.
        pill("Summer Festival", 0, kind="observance"),
        all_day("Cabin trip", 0),
        timed("Morning run", 7, 0, 45),
        timed("Recycling pickup", 8, 30, 15),
        timed("Team standup", 9, 15, 30),
        timed("Grocery run", 10, 30, 45),
        timed("Water the garden", 11, 45, 30),
        timed("Focus block", 13, 30, 90),  # in progress at 2 PM -> next-up tint
        # Enough upcoming that, after every past row rolls, the bottom "+N more"
        # trim still has to hide the last couple - both indicators in one frame.
        timed("School pickup", 15, 30, 15),
        timed("Vet appointment", 16, 45, 45),
        timed("Swim practice", 17, 30, 45),
        timed("Dinner reservation", 19, 0, 90),
        timed("Movie night", 20, 15, 105),
        timed("Evening walk", 21, 45, 30),
        # Upcoming days.
        all_day("Cabin trip", 1),  # the span repeats onto its second day
        timed("Farmers market", 9, 0, 60, plus_days=1),
        timed("Bike ride", 14, 0, 90, plus_days=1),
        pill("Independence Day", 2),
        timed("Neighborhood parade", 11, 0, 60, plus_days=2),
        timed("Fireworks picnic", 20, 30, 90, plus_days=2),
        timed("Oil change", 10, 0, 60, plus_days=3),
        # A fourth upcoming day so column 2 overflows into the "+N more days"
        # footer.
        timed("Library returns", 15, 0, 30, plus_days=4),
    ]
    assert events == sorted(events, key=lambda e: e["start"])  # contract: pre-sorted

    current: CurrentWeather = {
        "temp_f": 82,
        "feels_like_f": 85,
        "code": 2,
        **describe(2, is_day=True),
        "is_day": True,
        "humidity_pct": 52,
        "wind_mph": 7,
        "precip_prob_pct": 15,
        "high_f": 88,
        "low_f": 71,
        "sunrise": iso(now.replace(hour=5, minute=47, second=0, microsecond=0)),
        "sunset": iso(now.replace(hour=20, minute=29, second=0, microsecond=0)),
    }
    # (code, high, low, precip %): a dry/wet mix to exercise the precip line.
    forecast_days = [
        (0, 90, 72, 5),
        (95, 84, 70, 65),
        (61, 78, 66, 45),
        (2, 81, 68, 10),
    ]
    forecast: list[ForecastDay] = [
        {
            "date": day(i + 1),
            "code": code,
            **describe(code, is_day=True),
            "high_f": hi,
            "low_f": lo,
            "precip_prob_pct": pct,
            "precip_expected": is_wet(code),
        }
        for i, (code, hi, lo, pct) in enumerate(forecast_days)
    ]

    # Two zones on purpose. generated_at is in the server's zone: `_date_rolled`
    # compares its date against NY-now, and the fake zone can be on another day,
    # forcing a live refetch. fetched_at is in the fake zone because the
    # frontend renders its wall-clock as the "Updated" stamp.
    server_stamp = datetime.now(ZoneInfo("America/New_York")).isoformat(
        timespec="seconds"
    )
    display_stamp = iso(now)
    return {
        "generated_at": server_stamp,
        "clock_synced": True,
        "weather": {
            "ok": True,
            "fetched_at": display_stamp,
            "current": current,
            "forecast": forecast,
        },
        "calendar": {"ok": True, "fetched_at": display_stamp, "events": events},
    }


def wait_healthy(url: str, server: subprocess.Popen[bytes], tries: int = 50) -> None:
    """Poll until the server answers, failing if the child exits: otherwise a
    foreign server on the same port (e.g. a lingering `--serve`) would answer
    and the screenshot would capture the wrong app."""
    for _ in range(tries):
        if server.poll() is not None:
            raise RuntimeError(
                f"fixture server exited (code {server.returncode}) before "
                f"becoming healthy — is the port already in use, e.g. by a "
                f"running --serve session? Try --port."
            )
        try:
            with urllib.request.urlopen(url, timeout=1):
                return
        except (urllib.error.URLError, OSError):
            time.sleep(0.2)
    raise RuntimeError(f"server never became healthy at {url}")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Render the mockup screenshot (or serve the fixture-backed "
        "app) from fabricated, PII-free data."
    )
    parser.add_argument(
        "--theme",
        help="palette override: a stylesheet name from static/themes/ (no .css)",
    )
    parser.add_argument(
        "--layout",
        help="UI layout: a directory name under static/layouts/ (default classic)",
    )
    parser.add_argument(
        "--icon-pack",
        help="icon pack: a directory name under static/packs/ (default weather-icons)",
    )
    parser.add_argument(
        "--out",
        type=Path,
        help="screenshot path (default docs/mockup.png; a non-default --layout, "
        "--theme, and/or --icon-pack add a -<layout>-<theme>-<iconpack> suffix so "
        "renders don't clobber)",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=PORT,
        help=f"local port for the fixture server (default {PORT}); pick "
        "another when a --serve session already holds the default",
    )
    parser.add_argument(
        "--serve",
        action="store_true",
        help="keep the fixture-backed server running to browse interactively "
        "instead of screenshotting (fixture built in the LOCAL zone, so which "
        "marquee states show depends on the time of day)",
    )
    parser.add_argument(
        "--scale",
        type=int,
        default=2,
        help="device scale factor for the screenshot (default 2 -> a 2560x1600 "
        "png from the 1280x800 canvas); raise for a denser pixel-regression "
        "baseline",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if args.theme:
        themes_dir = REPO / "static" / "themes"
        if not (themes_dir / f"{args.theme}.css").is_file():
            names = ", ".join(sorted(p.stem for p in themes_dir.glob("*.css")))
            print(
                f"unknown theme {args.theme!r} — available: {names or '(none)'}",
                file=sys.stderr,
            )
            return 1
    if args.layout:
        layouts_dir = REPO / "static" / "layouts"
        if not (layouts_dir / args.layout).is_dir():
            names = ", ".join(
                sorted(p.name for p in layouts_dir.iterdir() if p.is_dir())
            )
            print(
                f"unknown layout {args.layout!r} — available: {names or '(none)'}",
                file=sys.stderr,
            )
            return 1
    if args.icon_pack:
        packs_dir = REPO / "static" / "packs"
        # Mirror the server's `_available_slugs`: a pack resolves only with an
        # index.js.
        if not (packs_dir / args.icon_pack / "index.js").is_file():
            names = ", ".join(
                sorted(
                    p.name for p in packs_dir.iterdir() if (p / "index.js").is_file()
                )
            )
            print(
                f"unknown icon pack {args.icon_pack!r} — available: {names or '(none)'}",
                file=sys.stderr,
            )
            return 1
    if not args.serve and not Path(CHROME).exists():
        print(f"Chrome not found at {CHROME!r} — set CHROME_BIN", file=sys.stderr)
        return 1
    # Non-default choices add a filename suffix so an experiment can't clobber
    # the README image.
    suffix = "-".join(
        part
        for part in (
            args.layout if args.layout and args.layout != "classic" else None,
            args.theme,
            args.icon_pack
            if args.icon_pack and args.icon_pack != "weather-icons"
            else None,
        )
        if part
    )
    out: Path = args.out or (OUT.with_name(f"mockup-{suffix}.png") if suffix else OUT)
    if args.serve:
        # The viewer's browser runs on real local time.
        local = datetime.now().astimezone().tzinfo
        assert local is not None
        tz_name, tz = "local", local
    else:
        tz_name, tz = fake_zone()
    with tempfile.TemporaryDirectory(prefix="mockup-cache-") as cache_dir:
        (Path(cache_dir) / "dashboard.json").write_text(json.dumps(build_doc(tz)))
        server_env = {**os.environ, "CACHE_DIR": cache_dir}
        if args.theme:
            server_env["THEME"] = args.theme
        if args.layout:
            server_env["LAYOUT"] = args.layout
        if args.icon_pack:
            server_env["ICON_PACK"] = args.icon_pack
        server = subprocess.Popen(
            [sys.executable, "-m", "uvicorn", "app.main:app", "--port", str(args.port)],
            cwd=REPO,
            env=server_env,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        try:
            wait_healthy(f"http://127.0.0.1:{args.port}/healthz", server)
            if args.serve:
                bits = [
                    f"{k}: {v}"
                    for k, v in (
                        ("layout", args.layout),
                        ("theme", args.theme),
                        ("icon pack", args.icon_pack),
                    )
                    if v
                ]
                note = f" ({', '.join(bits)})" if bits else ""
                print(f"serving http://127.0.0.1:{args.port}/{note} — Ctrl-C to stop")
                try:
                    server.wait()
                except KeyboardInterrupt:
                    pass
                return 0
            out.parent.mkdir(parents=True, exist_ok=True)
            chrome_args = [
                CHROME,
                "--headless",
                "--disable-gpu",
                "--window-size=1280,800",
                # crisp in the README; --scale raises it for a denser baseline
                f"--force-device-scale-factor={args.scale}",
                "--virtual-time-budget=6000",
            ]
            url = f"http://127.0.0.1:{args.port}/"
            env = {**os.environ, "TZ": tz_name}
            subprocess.run(
                [*chrome_args, f"--screenshot={out}", url],
                env=env,
                check=True,
                capture_output=True,
            )
            # Warn if the frame missed a marquee state, so a regression can't
            # silently regenerate a broken README image.
            dom = subprocess.run(
                [*chrome_args, "--dump-dom", url],
                env=env,
                check=True,
                capture_output=True,
                text=True,
            ).stdout
            # DOM strings each layout should render for this fixture; class names
            # differ per layout, so each needs its own set.
            layout_markers = {
                "classic": (" earlier", " more<", "is-next", "Cabin trip", "Independence Day"),
                # Single column that drops later days from the end: no roll-off.
                "hud": ("active", "Cabin trip", " more day"),
                # Two columns like classic, plus its own "● NOW" next-up tag.
                "swiss-mono": (" earlier", " more day", "● NOW", "Cabin trip", "Independence Day"),
            }
            # Classic's markers would warn spuriously on an unknown layout; skip.
            layout = args.layout or "classic"
            markers = layout_markers.get(layout)
            if markers is None:
                print(
                    f"note: no marker profile for layout {layout!r}, skipping frame check",
                    file=sys.stderr,
                )
            else:
                for marker in markers:
                    if marker not in dom:
                        print(
                            f"WARNING: {marker!r} missing from the rendered frame",
                            file=sys.stderr,
                        )
                if " earlier" in dom and dom.index(" earlier") < dom.index("Cabin trip"):
                    print(
                        "WARNING: '+N earlier' rendered ABOVE the all-day block",
                        file=sys.stderr,
                    )
        finally:
            server.terminate()
            server.wait(timeout=10)
    print(f"wrote {out} (clock pinned to {DISPLAY_HOUR}:00 via TZ={tz_name})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
