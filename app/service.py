"""The dashboard's control over its own systemd user service (impure edges).

Shared by the admin config Apply and (Phase 4) the restart action.
"""

from __future__ import annotations

import logging
import subprocess
from typing import Final

log = logging.getLogger("pi_dashboard.service")

_UNIT: Final = "pi-dashboard.service"

# A synchronous `systemctl --user restart` would SIGTERM the very process serving
# the HTTP reply. A transient timer in the user manager fires ~1s later instead,
# independent of this process, so the response flushes first.
_RESTART_CMD: Final = (
    "systemd-run",
    "--user",
    "--collect",
    "--on-active=1s",
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
