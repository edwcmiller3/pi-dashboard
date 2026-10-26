"""FastAPI entrypoint: a background loop refreshes weather + calendar into the
cache, `/api/data` serves the cached doc, and the remaining routes serve the
config-selected assets and the admin screen.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import os
import re
import stat
import tempfile
import uuid
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Final, Literal, TypedDict, TypeVar, cast
from zoneinfo import ZoneInfo

from fastapi import FastAPI
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, ConfigDict
from starlette.responses import Response
from starlette.types import Scope

from app import cache, service, stats
from app.config import settings
from app.contract import (
    DashboardDoc,
    SourceBlock,
    as_calendar_block,
    as_weather_block,
)
from app.envfile import EnvKey, with_values
from app.sources.calendar import get_calendar
from app.sources.weather import get_weather

log = logging.getLogger("pi_dashboard.refresh")

_CACHE_KEY: Final = "dashboard"
_DISPLAY_TZ: Final = "America/New_York"

# First post-failure retry delay; see `_backoff_delay`.
_BACKOFF_START_SECONDS: Final = 30

# Created by systemd-timesyncd once NTP-synced; the Pi has no RTC, so the clock
# is untrustworthy until then. Module-level so tests can repoint it.
_TIMESYNC_MARKER = Path("/run/systemd/timesync/synchronized")

# After a restart the client waits for /healthz to report a different boot id,
# so a reply from the not-yet-stopped old process can't pass for the new one.
_BOOT_ID: Final = uuid.uuid4().hex

B = TypeVar("B", bound=SourceBlock)


def _clock_synced() -> bool:
    """Whether the clock is NTP-synced. Without the timesyncd runtime dir (the
    dev Mac) we can't tell, so assume synced rather than warn falsely."""
    try:
        if not _TIMESYNC_MARKER.parent.is_dir():
            return True
        return _TIMESYNC_MARKER.exists()
    except OSError:
        return True


def _iso_age(iso: str | None, now: datetime) -> float | None:
    if not isinstance(iso, str):
        return None
    try:
        return (now - datetime.fromisoformat(iso)).total_seconds()
    except ValueError:
        return None


def _is_due(
    block: SourceBlock | None,
    ttl: int,
    now: datetime,
    force: bool,
    *,
    retry_floor: int,
) -> bool:
    """Whether a source should be refetched this tick.

    A failed block is due once `retry_floor` has passed since the last attempt,
    not every tick, so a down source isn't hammered while a weather outage has
    the loop in fast backoff.
    """
    if force or block is None:
        return True
    if not block.get("ok"):
        # Blocks cached before `attempted_at` existed fall back to `fetched_at`.
        last = block.get("attempted_at") or block.get("fetched_at")
        age = _iso_age(last, now)
        return age is None or age >= retry_floor
    age = _iso_age(block.get("fetched_at"), now)
    return age is None or age >= ttl


def _backoff_delay(failures: int, base: int) -> int:
    """Doubles per consecutive failure (`failures` >= 1), capped at the base
    tick so a sustained outage settles to the normal cadence."""
    return min(base, _BACKOFF_START_SECONDS << (failures - 1))


def _seconds_to_next_local_midnight(now: datetime) -> float:
    """Computed in UTC: subtracting aware datetimes with the same tzinfo returns
    the wall-clock difference, which is off by an hour across a DST change."""
    midnight = (now + timedelta(days=1)).replace(
        hour=0, minute=0, second=0, microsecond=0
    )
    return (
        midnight.astimezone(timezone.utc) - now.astimezone(timezone.utc)
    ).total_seconds()


def _date_rolled(prev_iso: str | None, now: datetime) -> bool:
    """Whether a prior doc's `generated_at` is on an earlier local day. Absent or
    unparseable -> False: every source is due then anyway."""
    if not isinstance(prev_iso, str):
        return False
    try:
        return datetime.fromisoformat(prev_iso).date() != now.date()
    except ValueError:
        return False


async def _refresh_source(
    fetch: Callable[[], Awaitable[B]],
    prior: B | None,
    ttl: int,
    now: datetime,
    *,
    force: bool,
    retry_floor: int,
    name: str,
) -> tuple[B, bool]:
    """Refresh one source if due, returning (block, failed); `failed` means an
    attempted fetch fell back to last-good. With no last-good, the error
    propagates."""
    if prior is not None and not _is_due(
        prior, ttl, now, force, retry_floor=retry_floor
    ):
        return prior, False
    try:
        block = await fetch()
    except Exception:
        log.exception("%s refresh failed", name)
        if prior is None:
            raise
        # Keep last-good data, flagged stale, stamping the attempt for `_is_due`.
        # The cast is sound: only `ok` and NotRequired keys change.
        stale = {
            **prior,
            "ok": False,
            "ttl": ttl,
            "attempted_at": now.isoformat(timespec="seconds"),
        }
        return cast(B, stale), True
    return cast(B, {**block, "ttl": ttl}), False


async def _refresh_once(force: bool = False, *, now: datetime | None = None) -> bool:
    """Refresh the due sources (each with its own last-good fallback) and cache
    the doc. Returns False if any attempted source fell back, to drive backoff.

    The calendar soft-fails in-band (`get_calendar` never raises for Proton), so
    only weather drives backoff; Proton's retry cadence is its `retry_floor`.
    """
    now = now or datetime.now(ZoneInfo(_DISPLAY_TZ))
    raw = await asyncio.to_thread(cache.read, _CACHE_KEY)
    # An absent/invalid block narrows to None, which makes that source due.
    prior = raw if isinstance(raw, dict) else {}
    prior_weather = as_weather_block(prior.get("weather"))
    prior_calendar = as_calendar_block(prior.get("calendar"))

    # The agenda window only rolls when sources refetch, so force a full refresh
    # on a new local day even if every source is within its TTL.
    force = force or _date_rolled(prior.get("generated_at"), now)

    weather, w_failed = await _refresh_source(
        get_weather,
        prior_weather,
        settings.weather_ttl_seconds,
        now,
        force=force,
        retry_floor=_BACKOFF_START_SECONDS,
        name="weather",
    )
    calendar, c_failed = await _refresh_source(
        lambda: get_calendar(now=now, last_good=prior_calendar),
        prior_calendar,
        settings.calendar_ttl_seconds,
        now,
        force=force,
        retry_floor=settings.calendar_ttl_seconds,
        name="calendar",
    )

    doc: DashboardDoc = {
        "generated_at": now.isoformat(timespec="seconds"),
        "clock_synced": _clock_synced(),
        "weather": weather,
        "calendar": calendar,
    }
    await asyncio.to_thread(cache.write, _CACHE_KEY, doc)
    return not (w_failed or c_failed)


# Serializes the background loop and POST /refresh so a manual refresh can't
# race a scheduled tick into a double-fetch or interleaved cache write.
_refresh_lock = asyncio.Lock()


async def _refresh_loop() -> None:
    """Never exits on a failing tick. Base cadence is the shortest source TTL,
    shortened by backoff after a failure."""
    failures = 0
    while True:
        now = datetime.now(ZoneInfo(_DISPLAY_TZ))
        base = min(settings.weather_ttl_seconds, settings.calendar_ttl_seconds)
        try:
            async with _refresh_lock:
                healthy = await _refresh_once(now=now)
        except Exception:
            log.exception("refresh tick failed; keeping last-good cache")
            healthy = False
        if healthy:
            failures = 0
            delay = float(base)
        else:
            failures += 1
            delay = float(_backoff_delay(failures, base))
        # Wake just after local midnight so the agenda rolls on time.
        delay = min(delay, _seconds_to_next_local_midnight(now) + 1.0)
        await asyncio.sleep(delay)


def _loop_exited(task: asyncio.Future[None]) -> None:
    # Fires only on shutdown cancellation in normal operation; log loudly otherwise.
    if not task.cancelled():
        log.error("refresh loop exited unexpectedly: %r", task.exception())


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    if not settings.proton_ics_url:
        # Otherwise invisible on a headless Pi: holidays still show, so nothing
        # points at the missing personal events.
        log.warning(
            "PROTON_ICS_URL is not set — personal calendar events are disabled "
            "(holidays/observances still show). Set it in .env to enable."
        )
    _warn_on_unknown_layout()
    _warn_on_unknown_pack()
    # Confirms the polkit rule reaches a session-less boot-time service (expect
    # "yes"). WARNING because nothing configures logging, so INFO is dropped.
    log.warning("logind CanReboot: %s", await asyncio.to_thread(service.can_reboot))
    task = asyncio.create_task(_refresh_loop())
    app.state.refresh_task = task  # strong ref, or the task can be GC'd
    task.add_done_callback(_loop_exited)
    try:
        yield
    finally:
        task.cancel()


app = FastAPI(title="pi-dashboard", version="0.1.0", lifespan=lifespan)


@app.get("/healthz")
def healthz() -> JSONResponse:
    """Liveness probe; `boot` changes on every process start."""
    return JSONResponse({"status": "ok", "boot": _BOOT_ID})


@app.get("/api/data")
def api_data() -> JSONResponse:
    """The dashboard doc; 503 until the first tick warms the cache."""
    doc = cache.read(_CACHE_KEY)
    if doc is None:
        return JSONResponse({"detail": "warming up"}, status_code=503)
    if isinstance(doc, dict) and (
        as_weather_block(doc.get("weather")) is None
        or as_calendar_block(doc.get("calendar")) is None
    ):
        # Never log the doc itself (calendar PII). Serve it anyway so the
        # dashboard degrades rather than blanks.
        log.warning("cached dashboard block failed contract validation; serving as-is")
    # Live value, so the boot tick's stale False clears within one poll of NTP
    # sync rather than lingering until the next refresh tick.
    if isinstance(doc, dict):
        doc = {**doc, "clock_synced": _clock_synced()}
    return JSONResponse(doc)


@app.post("/refresh")
async def refresh() -> JSONResponse:
    """Force an immediate refresh of every source."""
    async with _refresh_lock:
        try:
            await _refresh_once(force=True)
        except Exception:
            log.exception("manual refresh failed")
            return JSONResponse({"detail": "refresh failed"}, status_code=502)
    return JSONResponse({"status": "refreshed"})


class _NoCacheStaticFiles(StaticFiles):
    """`no-cache` makes the kiosk revalidate each load: unchanged assets are a
    cheap 304, and a deploy is picked up without a hard refresh."""

    async def get_response(self, path: str, scope: Scope) -> Response:
        response = await super().get_response(path, scope)
        response.headers["Cache-Control"] = "no-cache"
        return response


_static_dir = Path(__file__).resolve().parent.parent / "static"

# Slug settings are interpolated into filesystem paths, so only bare slugs pass.
_SLUG_RE: Final = re.compile(r"[A-Za-z0-9_-]+")

# Same revalidate-on-load contract as the static bundle.
_NO_CACHE: Final = {"Cache-Control": "no-cache"}


def _normalized(name: str) -> str:
    """Strip and lowercase a slug setting. The dev Mac's filesystem is
    case-insensitive but the Pi's isn't, so LAYOUT=HUD would work in dev yet
    fall back on the wall; every bundled asset dir is lowercase."""
    return name.strip().lower()


def _valid_slug(name: str) -> bool:
    """Warns on a non-empty non-slug; empty is the quiet default."""
    if _SLUG_RE.fullmatch(name):
        return True
    if name:
        log.warning("%r is not a bare slug; ignoring", name)
    return False


def _builtin_slug_css(subdir: str, slug: str, leaf: str) -> str:
    """The built-in default's stylesheet, the fallback when a slug won't resolve:
    the matching .js route falls back to the built-in module, which would render
    unstyled without it. Empty (never a 500) if the built-in file is missing."""
    try:
        return (_static_dir / subdir / slug / f"{leaf}.css").read_text(encoding="utf-8")
    except OSError:
        log.warning("%s %s.css is missing; serving empty %s css", slug, leaf, leaf)
        return ""


def _serve_slug_css(
    name: str,
    subdir: str,
    *,
    leaf: str | None = None,
    fallback: Callable[[], str] = lambda: "",
) -> Response:
    """Serve static/<subdir>/<name>.css, or <name>/<leaf>.css when `leaf` is
    given. A bad slug or unreadable file degrades to `fallback()` - the kiosk
    must never lose the dashboard over a bad config value. Read per request so
    an edit shows on next reload.
    """
    name = _normalized(name)  # case/space-fold so HUD resolves like hud on the Pi
    if _valid_slug(name):
        rel = f"{name}.css" if leaf is None else f"{name}/{leaf}.css"
        path = _static_dir / subdir / rel
        try:
            body = path.read_text(encoding="utf-8")
        except FileNotFoundError:
            log.info("%s not found; ignoring", path)
            body = fallback()
        except OSError:
            log.warning("%s is unreadable; ignoring", path)
            body = fallback()
    else:
        body = fallback()
    return Response(body, media_type="text/css", headers=_NO_CACHE)


def _serve_module(
    name: str, subdir: str, default: str, export: str, *, leaf: str = "index.js"
) -> Response:
    """A generated one-line ES module re-exporting `export` from the selected
    slug's `leaf`. A bad slug or missing module falls back to `default`: a
    re-export of a missing module 404s the module graph at load time, which
    app.js can't catch, blanking the kiosk."""
    name = _normalized(name)  # case/space-fold so HUD resolves like hud on the Pi
    slug = name if _valid_slug(name) else default
    if slug != default and not (_static_dir / subdir / slug / leaf).is_file():
        log.warning(
            "%s %r has no %s module; falling back to %r", subdir, slug, leaf, default
        )
        slug = default
    if not (_static_dir / subdir / slug / leaf).is_file():
        # Broken deploy: an inline empty export is survivable by app.js's
        # usage-level try/catch, unlike a load-time 404.
        log.warning(
            "%s default %r has no %s module; serving inline stub", subdir, default, leaf
        )
        body = f"export const {export} = {{}};\n"
        return Response(body, media_type="text/javascript", headers=_NO_CACHE)
    body = f'export {{{export}}} from "./{subdir}/{slug}/{leaf}";\n'
    return Response(body, media_type="text/javascript", headers=_NO_CACHE)


def _available_slugs(subdir: str) -> list[str]:
    """Dirs under static/<subdir>/ with an index.js; empty if unreadable."""
    try:
        return sorted(
            p.name
            for p in (_static_dir / subdir).iterdir()
            if (p / "index.js").is_file()
        )
    except OSError:
        return []


def _warn_on_unknown_slug(
    subdir: str, selected: str, default: str, *, label: str, noun: str
) -> None:
    """Log once at startup when a slug setting won't resolve, so a typo shows in
    the journal instead of silently rendering the default on a headless wall. A
    case/space variant that the routes fold (HUD -> hud) doesn't warn."""
    name = _normalized(selected)
    if not name or name == default:
        return
    if not _valid_slug(name):
        return  # _valid_slug already warned
    if not (_static_dir / subdir / name / "index.js").is_file():
        log.warning(
            "%s=%r matches no %s under static/%s (have: %s); serving %s",
            label,
            selected,
            noun,
            subdir,
            ", ".join(_available_slugs(subdir)) or "none",
            default,
        )


def _warn_on_unknown_layout() -> None:
    _warn_on_unknown_slug(
        "layouts", settings.layout, "classic", label="LAYOUT", noun="layout"
    )


def _warn_on_unknown_pack() -> None:
    _warn_on_unknown_slug(
        "packs", settings.icon_pack, "weather-icons", label="ICON_PACK", noun="pack"
    )


@app.get("/theme.css")
def theme_css() -> Response:
    """The THEME palette override, linked last so its `:root` wins; empty means
    the built-in palette."""
    return _serve_slug_css(settings.theme, "themes")


@app.get("/layout.css")
def layout_css() -> Response:
    """The LAYOUT stylesheet; cascade is base < layout < theme. Falls back to
    classic's, not empty."""
    return _serve_slug_css(
        settings.layout,
        "layouts",
        leaf="layout",
        fallback=lambda: _builtin_slug_css("layouts", "classic", "layout"),
    )


@app.get("/layout.js")
def layout_js() -> Response:
    """ES module selecting the layout. Must be text/javascript: strict module
    loading silently refuses a wrong MIME, blanking the kiosk."""
    return _serve_module(settings.layout, "layouts", "classic", "layout")


@app.get("/pack.css")
def pack_css() -> Response:
    """The ICON_PACK stylesheet. Falls back to weather-icons', not empty."""
    return _serve_slug_css(
        settings.icon_pack,
        "packs",
        leaf="pack",
        fallback=lambda: _builtin_slug_css("packs", "weather-icons", "pack"),
    )


@app.get("/pack.js")
def pack_js() -> Response:
    """ES module selecting the icon pack; must be text/javascript, as /layout.js."""
    return _serve_module(settings.icon_pack, "packs", "weather-icons", "iconPack")


@app.get("/admin.css")
def admin_css() -> Response:
    """The layout's admin-skin stylesheet; falls back to classic's, as /admin.js."""
    return _serve_slug_css(
        settings.layout,
        "layouts",
        leaf="admin",
        fallback=lambda: _builtin_slug_css("layouts", "classic", "admin"),
    )


@app.get("/admin.js")
def admin_js() -> Response:
    """ES module selecting the layout's admin skin; falls back to classic's."""
    return _serve_module(
        settings.layout, "layouts", "classic", "admin", leaf="admin.js"
    )


# ── admin config: the three presentation knobs ──────────────────────────────

ConfigKey = Literal["layout", "theme", "icon_pack"]

_CONFIG_ENV_KEYS: Final[dict[ConfigKey, EnvKey]] = {
    "layout": "LAYOUT",
    "theme": "THEME",
    "icon_pack": "ICON_PACK",
}

# The CWD-relative file Settings reads. Module-level so tests can repoint it.
_ENV_FILE = Path(".env")


class ConfigKnob(TypedDict):
    current: str
    options: list[str]


class AdminConfig(TypedDict):
    layout: ConfigKnob
    theme: ConfigKnob
    icon_pack: ConfigKnob


class ConfigUpdate(BaseModel):
    """Staged values from the admin panel; an omitted knob is unchanged. Unknown
    keys are rejected so a typo can't pass as a successful no-op."""

    model_config = ConfigDict(extra="forbid")

    layout: str | None = None
    theme: str | None = None
    icon_pack: str | None = None


def _available_themes() -> list[str]:
    """"" (built-in palette) plus each stylesheet stem under static/themes/."""
    try:
        stems = sorted(
            p.stem for p in (_static_dir / "themes").iterdir() if p.suffix == ".css"
        )
    except OSError:
        stems = []
    return ["", *stems]


def _selectable(names: list[str]) -> list[str]:
    """Names a setting can resolve to (routes lowercase it) and that are safe to
    write bare into .env."""
    return [n for n in names if _SLUG_RE.fullmatch(n) and n == n.lower()]


def _knob(raw: str, options: list[str], default: str) -> ConfigKnob:
    # "current" is what actually renders: an unresolvable value fail-softs to
    # the built-in default, so report that rather than the typo.
    name = _normalized(raw)
    return {"current": name if name in options else default, "options": options}


def _admin_config() -> AdminConfig:
    return {
        "layout": _knob(
            settings.layout, _selectable(_available_slugs("layouts")), "classic"
        ),
        # _selectable drops "" (not a slug); the built-in palette is re-added first.
        "theme": _knob(settings.theme, ["", *_selectable(_available_themes())], ""),
        "icon_pack": _knob(
            settings.icon_pack, _selectable(_available_slugs("packs")), "weather-icons"
        ),
    }


def _write_atomic(path: Path, text: str) -> None:
    """Atomic replace that keeps the file's mode (.env holds a secret, often
    0600), so a crash or full disk can't leave a truncated .env."""
    try:
        mode = stat.S_IMODE(path.stat().st_mode)
    except FileNotFoundError:
        mode = 0o600
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="") as f:
            f.write(text)
            f.flush()
            os.fsync(f.fileno())
        os.chmod(tmp, mode)
        os.replace(tmp, path)
    except BaseException:
        with contextlib.suppress(OSError):
            os.unlink(tmp)
        raise


def _read_env(path: Path) -> str:
    # newline="" keeps CRLF intact so untouched lines round-trip byte for byte.
    try:
        with path.open(encoding="utf-8", newline="") as f:
            return f.read()
    except FileNotFoundError:
        return ""


@app.get("/api/admin/config")
def admin_config() -> JSONResponse:
    """The three knobs only - current value + selectable options. Built from a
    whitelist, so the secret and every other setting are structurally absent."""
    return JSONResponse(_admin_config())


@app.post("/api/admin/config")
def admin_config_apply(update: ConfigUpdate) -> JSONResponse:
    """Validate, write only the diff to .env, and schedule a restart to load it.
    An empty diff is a no-op."""
    config = _admin_config()
    staged: dict[ConfigKey, str | None] = {
        "layout": update.layout,
        "theme": update.theme,
        "icon_pack": update.icon_pack,
    }
    for key, value in staged.items():
        if value is not None and value not in config[key]["options"]:
            return JSONResponse({"detail": f"unknown {key}: {value!r}"}, status_code=400)
    changes: dict[EnvKey, str] = {
        _CONFIG_ENV_KEYS[key]: value
        for key, value in staged.items()
        if value is not None and value != config[key]["current"]
    }
    if not changes:
        return JSONResponse({"restarted": False})
    try:
        _write_atomic(_ENV_FILE, with_values(_read_env(_ENV_FILE), changes))
    except (OSError, UnicodeError):
        log.exception("could not write %s", _ENV_FILE)
        return JSONResponse({"detail": "could not save settings"}, status_code=500)
    log.info("admin applied %s; restarting", ", ".join(sorted(changes)))
    if not service.restart_dashboard():
        return JSONResponse(
            {"detail": "saved, but the restart failed - restart the service to apply"},
            status_code=500,
        )
    return JSONResponse({"restarted": True, "boot": _BOOT_ID})


# ── admin stats: device health ──────────────────────────────────────────────


@app.get("/api/admin/stats")
def admin_stats() -> JSONResponse:
    """Sync on purpose: the ~0.1s CPU sample blocks a threadpool worker, not the
    event loop. Never 500s."""
    try:
        snapshot = stats.collect()
    except Exception:
        log.exception("stats collection failed")
        snapshot = stats.UNAVAILABLE
    return JSONResponse(snapshot, headers={"Cache-Control": "no-store"})


# ── admin actions: restart the dashboard, reboot the Pi ─────────────────────


class ActionRequest(BaseModel):
    """An action takes no options. Requiring a JSON body (even `{}`) rejects
    cross-origin "simple" POSTs, which can't send application/json."""

    model_config = ConfigDict(extra="forbid")


@app.post("/api/admin/restart")
def admin_restart(_: ActionRequest) -> JSONResponse:
    """The reply carries this process's boot id so the client can wait for a new
    one."""
    log.info("admin requested a dashboard restart")
    if not service.restart_dashboard():
        return JSONResponse({"detail": "the restart failed"}, status_code=500)
    return JSONResponse({"restarted": True, "boot": _BOOT_ID})


@app.get("/api/admin/reboot")
def admin_reboot_available() -> JSONResponse:
    """Whether the Reboot button can work (logind CanReboot == "yes")."""
    return JSONResponse(
        {"available": service.reboot_available()},
        headers={"Cache-Control": "no-store"},
    )


_REBOOT_FAILED: Final[dict[service.RebootOutcome, tuple[int, str]]] = {
    "unavailable": (503, "reboot unavailable - is the polkit rule installed?"),
    "failed": (500, "the reboot request failed"),
}


@app.post("/api/admin/reboot")
def admin_reboot(_: ActionRequest) -> JSONResponse:
    """200 only once logind accepted it, so the client never shows "rebooting"
    for a reboot that won't happen."""
    log.warning("admin requested a reboot")
    outcome = service.reboot()
    if outcome == "rebooting":
        return JSONResponse({"rebooting": True})
    status, detail = _REBOOT_FAILED[outcome]
    return JSONResponse({"detail": detail}, status_code=status)


# Mounted last so every route above takes precedence over the catch-all.
app.mount("/", _NoCacheStaticFiles(directory=_static_dir, html=True), name="static")
