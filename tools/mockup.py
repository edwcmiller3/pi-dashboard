"""Render the README mockup screenshot from fabricated, PII-free data.

Runs the real app locally against an injected fixture cache and captures it
with headless Chrome into docs/mockup.png:

    uv run python -m tools.mockup

Palette preview: `--theme <name>` runs the server with THEME=<name> (a
stylesheet in static/themes/), screenshotting to docs/mockup-<name>.png so the
README image is never clobbered by a theme experiment (override with --out).
`--serve` skips Chrome and keeps the fixture-backed server running to browse
interactively - in that mode the fixture is built in the machine's LOCAL zone
so event times line up with the real browser clock, which means which marquee
states appear (next-up, roll-off) depends on the time of day you run it.

Every stamp in the fixture is fresh, so the server's boot refresh tick sees
both sources within TTL and serves the fixture verbatim - no live fetch, no
.env / PROTON_ICS_URL needed, and nothing personal on screen (all event titles
and weather values are made up; icons/labels/precip gating come from the real
`weather_codes` module so they stay contract-true).

The one moving part is the clock: the page's big clock and the "today
awareness" logic (next-up highlight, roll-off) key off the BROWSER's local time,
so Chrome runs under a fixed-offset TZ (Etc/GMT±N) chosen so its local hour reads
14 (2 PM) whenever this is regenerated, and the fixture's event times are written
in that same zone - mid-afternoon, deterministic modulo the minute.

The frame deliberately exercises: current-weather hero; forecast cards with
wet (precip line) and dry days; today's column with an observance pill, a
multi-day all-day span, rolled-off past events ("+N earlier", sitting below
the pill/all-day block), the in-progress next-up highlight, upcoming events,
and enough of them that the bottom "+N more" trim fires too; column 2 with the
span repeating, a holiday pill, further days, and the "+N more days" footer;
fresh status dots + Updated stamp. Mutually-exclusive states (quiet day, stale
dots, clock warning, cold boot) can't share the frame and are not shown; nor
can a PARTIALLY-rolled day (a visible past event), which the bottom "+N more"
precludes by design - the trim only runs once every past row has rolled.
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
    """A fixed-offset zone in which the CURRENT local hour is DISPLAY_HOUR.

    Returns (IANA name for Chrome's TZ env var, matching Python timezone).
    Etc/GMT names carry the INVERTED sign (Etc/GMT+4 means UTC-4).
    """
    offset = (DISPLAY_HOUR - datetime.now(timezone.utc).hour) % 24
    if offset > 12:
        offset -= 24  # keep within the Etc/GMT-12..+11 range
    name = "Etc/GMT" if offset == 0 else f"Etc/GMT{-offset:+d}"
    return name, timezone(timedelta(hours=offset))


def build_doc(tz: tzinfo) -> DashboardDoc:
    """The fixture DashboardDoc - fabricated values, contract-true shapes."""
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
        # A fourth upcoming day so column 2 genuinely overflows and the "+N more
        # days" footer fires. (It used to fire with three days only because the
        # old fit pass measured with its probe footer attached, which could push
        # an exactly-fitting column over budget - planColumnFit fixed that, so
        # the frame needs real overflow to show the footer.)
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
    # (code, high, low, precip %): a dry/wet mix so the conditional precip line
    # shows on some cards and stays absent on others.
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

    # Two zones on purpose. generated_at must be in the server's display zone:
    # `_date_rolled` compares its DATE against NY-now, and the fake zone can sit
    # on a different calendar day - which would force a live refetch. fetched_at
    # must be in the FAKE zone: the frontend renders its literal wall-clock as
    # the "Updated" stamp, which has to agree with the pinned page clock. Both
    # are aware stamps, so the freshness *age* math is epoch-correct either way.
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
    """Poll `url` until the fixture server answers - watching the CHILD too.

    If the child exits while we poll (typically a bind failure because another
    server - e.g. a lingering `--serve` session - already holds the port), fail
    loudly. Without that check a foreign server on the same port answers the
    health probe and the screenshot silently captures the WRONG app state.
    """
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
        # Mirror the server's _available_packs rule: a pack dir only resolves at
        # runtime if it carries an index.js module, so a dir lacking one must be
        # rejected here too (an is_dir() check alone would pass then fail to serve).
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
    # A non-default layout, theme, and/or icon pack each default to their own file
    # so a layout×theme×pack experiment can never silently clobber the README image
    # (nor can a HUD render clobber the classic PNG). classic and weather-icons are
    # the defaults, so they add no suffix - an unthemed classic render on the
    # default pack stays docs/mockup.png.
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
        # Interactive browsing: the viewer's browser runs on real local time, so
        # build the fixture in the local zone to keep event times aligned.
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
            # Sanity-check the frame actually exercised the marquee states, so a
            # regression can't silently regenerate a broken README image.
            dom = subprocess.run(
                [*chrome_args, "--dump-dom", url],
                env=env,
                check=True,
                capture_output=True,
                text=True,
            ).stdout
            # Per-layout marquee markers: the DOM strings each layout is expected
            # to render for this fixture. The classic-specific class names (e.g.
            # .event.is-next) don't exist in the HUD DOM, so a hardcoded classic
            # set emits spurious WARNINGs against a HUD render - give each layout
            # its own set. Non-blocking prints, not test failures. Both layouts
            # place the roll-off ("+N earlier") BELOW the all-day block.
            layout_markers = {
                "classic": (" earlier", " more<", "is-next", "Cabin trip", "Independence Day"),
                # HUD is a single column that protects today and drops later days
                # from the end, so its marquee is the next-up row (.ev.active), the
                # all-day span, and the "+N more days" footer - not the classic
                # two-column roll-off vocabulary (.is-next / a trimmed today).
                "hud": ("active", "Cabin trip", " more day"),
                # swiss-mono is a two-column layout like classic (today alone in
                # col1 with the roll-off vocabulary; upcoming days in col2 dropping
                # from the end into a "+N more days" footer), plus its own "● NOW"
                # tag on the next-up row. Guards the fit shell: a regressed column
                # fit would drop the "+N more day" footer and this would warn.
                "swiss-mono": (" earlier", " more day", "● NOW", "Cabin trip", "Independence Day"),
            }
            # An unknown/future layout has no marker profile; running classic's set
            # against it would emit spurious WARNINGs, so skip the check entirely
            # rather than defaulting to classic's markers.
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
