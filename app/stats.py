"""Device health for the admin screen's health panel (GET /api/admin/stats).

The decoders are pure; collect() is the impure edge - psutil for the
cross-platform families, `vcgencmd` (Pi-only) for temperature and throttle.
Every field fails soft to None ("unavailable") on its own, so the dev Mac (no
vcgencmd) or any broken probe degrades one tile, never the endpoint.
"""

from __future__ import annotations

import ipaddress
import logging
import re
import socket
import subprocess
import time
from collections.abc import Callable, Mapping, Sequence
from types import MappingProxyType
from typing import Final, Literal, Protocol, TypedDict, TypeVar

import psutil

log = logging.getLogger("pi_dashboard.stats")

ThrottleFlag = Literal[
    "under-voltage", "arm-frequency-capped", "throttled", "soft-temp-limit"
]

# `vcgencmd get_throttled`: bits 0-3 are the live state, the same flags 16 bits
# up are sticky since boot. Healthy is 0x0.
_THROTTLE_BITS: Final[Mapping[int, ThrottleFlag]] = MappingProxyType(
    {
        0: "under-voltage",
        1: "arm-frequency-capped",
        2: "throttled",
        3: "soft-temp-limit",
    }
)
_STICKY_SHIFT: Final = 16

_THROTTLED_RE: Final = re.compile(r"throttled=(0x[0-9a-fA-F]+)")
_TEMP_RE: Final = re.compile(r"temp=(\d+(?:\.\d+)?)'C")


class ThrottleState(TypedDict):
    flag: ThrottleFlag
    now: bool
    occurred: bool


class Throttle(TypedDict):
    raw: str
    flags: list[ThrottleState]


class Usage(TypedDict):
    used: int
    total: int


class Network(TypedDict):
    iface: str
    ip: str
    netmask: str | None
    prefix: int | None


class Stats(TypedDict):
    cpu_percent: float | None
    memory: Usage | None
    disk: Usage | None
    uptime_s: int | None
    host: str | None
    temp_c: float | None
    throttle: Throttle | None
    network: Network | None


UNAVAILABLE: Final[Stats] = {
    "cpu_percent": None,
    "memory": None,
    "disk": None,
    "uptime_s": None,
    "host": None,
    "temp_c": None,
    "throttle": None,
    "network": None,
}


class _Addr(Protocol):
    """The slice of psutil's snicaddr pick_network reads."""

    @property
    def family(self) -> int: ...
    @property
    def address(self) -> str: ...
    @property
    def netmask(self) -> str | None: ...


def decode_throttled(value: int) -> Throttle:
    """Named flags for each set bit (live or sticky); unmapped bits stay in raw."""
    flags: list[ThrottleState] = [
        {
            "flag": name,
            "now": bool(value >> bit & 1),
            "occurred": bool(value >> (bit + _STICKY_SHIFT) & 1),
        }
        for bit, name in _THROTTLE_BITS.items()
        if value >> bit & 1 or value >> (bit + _STICKY_SHIFT) & 1
    ]
    return {"raw": hex(value), "flags": flags}


def parse_throttled(out: str) -> Throttle | None:
    m = _THROTTLED_RE.search(out)
    return decode_throttled(int(m[1], 16)) if m else None


def parse_temp(out: str) -> float | None:
    m = _TEMP_RE.search(out)
    return float(m[1]) if m else None


def _prefix(netmask: str | None) -> int | None:
    if netmask is None:
        return None
    try:
        return ipaddress.IPv4Network(f"0.0.0.0/{netmask}").prefixlen
    except ValueError:
        return None


def pick_network(addrs: Mapping[str, Sequence[_Addr]]) -> Network | None:
    """The first interface (in OS order) with a routable IPv4 address - not
    loopback, not link-local (169.254/16, i.e. DHCP never answered)."""
    for iface, entries in addrs.items():
        for a in entries:
            if a.family != socket.AF_INET:
                continue
            ip = ipaddress.IPv4Address(a.address)
            if ip.is_loopback or ip.is_link_local:
                continue
            return {
                "iface": iface,
                "ip": a.address,
                "netmask": a.netmask,
                "prefix": _prefix(a.netmask),
            }
    return None


def _vcgencmd(command: str) -> str | None:
    """stdout of `vcgencmd <command>`, or None when absent (off-Pi) or failing."""
    proc = subprocess.run(
        ("vcgencmd", command), capture_output=True, text=True, timeout=2, check=False
    )
    return proc.stdout if proc.returncode == 0 else None


T = TypeVar("T")


def _soft(name: str, probe: Callable[[], T | None]) -> T | None:
    try:
        return probe()
    except Exception:
        # Debug, not warning: off-Pi this fires on every 5s poll by design.
        log.debug("stats probe %s unavailable", name, exc_info=True)
        return None


def _memory() -> Usage:
    vm = psutil.virtual_memory()
    # total - available, not vm.used: what an operator means by "in use", and
    # consistent across Linux and macOS (whose `used` excludes reclaimable pages).
    return {"used": vm.total - vm.available, "total": vm.total}


def _disk() -> Usage:
    du = psutil.disk_usage("/")
    return {"used": du.used, "total": du.total}


def _temp() -> float | None:
    out = _vcgencmd("measure_temp")
    return parse_temp(out) if out is not None else None


def _throttle() -> Throttle | None:
    out = _vcgencmd("get_throttled")
    return parse_throttled(out) if out is not None else None


def collect() -> Stats:
    """A fresh health snapshot. Blocks ~0.1s sampling CPU; never raises."""
    return {
        "cpu_percent": _soft("cpu", lambda: psutil.cpu_percent(interval=0.1)),
        "memory": _soft("memory", _memory),
        "disk": _soft("disk", _disk),
        "uptime_s": _soft("uptime", lambda: int(time.time() - psutil.boot_time())),
        "host": _soft("host", socket.gethostname),
        "temp_c": _soft("temp", _temp),
        "throttle": _soft("throttle", _throttle),
        "network": _soft("network", lambda: pick_network(psutil.net_if_addrs())),
    }
