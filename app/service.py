"""The dashboard's control over its own systemd user service (impure edges).

Shared by the admin config Apply and the admin device actions (restart, reboot).
"""

from __future__ import annotations

import logging
import re
import subprocess
from typing import Final, Literal

log = logging.getLogger("pi_dashboard.service")

_UNIT: Final = "pi-dashboard.service"

# A synchronous `systemctl --user restart` would SIGTERM the very process serving
# the HTTP reply. A transient timer in the user manager fires ~1s later instead,
# independent of this process, so the response flushes first. AccuracySec pins it:
# the 1min default let systemd coalesce the fire to a fixed second of the minute,
# ~30s late on average.
_RESTART_CMD: Final = (
    "systemd-run",
    "--user",
    "--collect",
    "--on-active=1s",
    "--timer-property=AccuracySec=100ms",
    "systemctl",
    "--user",
    "restart",
    _UNIT,
)


def restart_dashboard() -> bool:
    """Schedule a restart of the dashboard service; True once it is scheduled.
    Never raises - False when systemd-run is absent (the dev Mac) or fails."""
    try:
        proc = subprocess.run(
            _RESTART_CMD, capture_output=True, text=True, timeout=10, check=False
        )
    except (OSError, subprocess.SubprocessError):
        log.exception("could not schedule the dashboard restart")
        return False
    if proc.returncode != 0:
        log.error(
            "systemd-run exited %d scheduling the restart: %s",
            proc.returncode,
            proc.stderr.strip(),
        )
        return False
    return True


# Reboot goes through logind over D-Bus, authorized by the polkit rule in
# deploy/49-pi-dashboard-reboot.rules. Non-interactive, so a missing rule fails
# fast with "Interactive authentication required" instead of waiting on an
# authentication agent a kiosk doesn't have.
_LOGIND: Final = (
    "busctl",
    "--allow-interactive-authorization=no",
    "call",
    "org.freedesktop.login1",
    "/org/freedesktop/login1",
    "org.freedesktop.login1.Manager",
)

# The polkit denials; anything else is a real failure worth a 500.
_DENIED: Final = ("Interactive authentication required", "Access denied")

RebootOutcome = Literal["rebooting", "unavailable", "failed"]


def _logind(*call: str) -> subprocess.CompletedProcess[str]:
    """Run one logind Manager method; raises as subprocess.run does."""
    return subprocess.run(
        (*_LOGIND, *call), capture_output=True, text=True, timeout=5, check=False
    )


def parse_can_reboot(stdout: str) -> str | None:
    """busctl prints a string reply as `s "yes"`; anything else is None."""
    match = re.fullmatch(r's "([a-z-]+)"', stdout.strip())
    return match.group(1) if match else None


def can_reboot() -> str | None:
    """logind's CanReboot answer for this user ("yes", "challenge", "no", "na"),
    or None when it can't be asked. Never raises."""
    try:
        proc = _logind("CanReboot")
    except FileNotFoundError:
        return None  # no busctl: the dev Mac
    except (OSError, subprocess.SubprocessError):
        log.exception("could not ask logind CanReboot")
        return None
    return parse_can_reboot(proc.stdout) if proc.returncode == 0 else None


def reboot_available() -> bool:
    """True only on "yes": "challenge" means a password prompt, which the kiosk
    can't answer (the polkit rule isn't in place)."""
    return can_reboot() == "yes"


def reboot() -> RebootOutcome:
    """Ask logind to reboot now. Never raises: "unavailable" when polkit denies
    it or busctl is absent (the dev Mac), "failed" on anything else."""
    try:
        proc = _logind("Reboot", "b", "false")
    except FileNotFoundError:
        return "unavailable"
    except (OSError, subprocess.SubprocessError):
        log.exception("could not request the reboot")
        return "failed"
    if proc.returncode == 0:
        return "rebooting"
    stderr = proc.stderr.strip()
    if any(reason in stderr for reason in _DENIED):
        log.warning("reboot denied by polkit: %s", stderr)
        return "unavailable"
    log.error("busctl exited %d requesting the reboot: %s", proc.returncode, stderr)
    return "failed"
