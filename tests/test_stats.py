"""Device health for the admin panel: app/stats.py and GET /api/admin/stats.

The pure decoders (throttle bits, vcgencmd output, interface pick) are tested
directly; collect() is tested with every probe broken to prove it fails soft
per field and never raises - the dev-Mac shape (no vcgencmd) included.
"""

from __future__ import annotations

import socket
import subprocess
import time
import re
from collections.abc import Sequence
from pathlib import Path
from typing import Any, NamedTuple, get_args

import psutil
import pytest
from fastapi.testclient import TestClient

from app import stats
from app.main import app
from app.stats import (
    Throttle,
    decode_throttled,
    parse_temp,
    parse_throttled,
    pick_network,
)

# ── throttle decode ──────────────────────────────────────────────────────────


def test_throttle_zero_is_healthy() -> None:
    healthy: Throttle = {"raw": "0x0", "flags": []}
    assert decode_throttled(0x0) == healthy


def test_throttle_0x50005_is_under_voltage_and_throttled_now_and_earlier() -> None:
    expected: Throttle = {
        "raw": "0x50005",
        "flags": [
            {"flag": "under-voltage", "now": True, "occurred": True},
            {"flag": "throttled", "now": True, "occurred": True},
        ],
    }
    assert decode_throttled(0x50005) == expected


def test_throttle_sticky_bit_alone_is_occurred_not_now() -> None:
    assert decode_throttled(0x80000)["flags"] == [
        {"flag": "soft-temp-limit", "now": False, "occurred": True}
    ]


@pytest.mark.parametrize(
    ("bit", "flag"),
    [
        (0, "under-voltage"),
        (1, "arm-frequency-capped"),
        (2, "throttled"),
        (3, "soft-temp-limit"),
    ],
)
def test_throttle_each_live_bit_names_its_flag(bit: int, flag: str) -> None:
    assert decode_throttled(1 << bit)["flags"] == [
        {"flag": flag, "now": True, "occurred": False}
    ]


def test_throttle_unmapped_bits_are_ignored_but_kept_in_raw() -> None:
    expected: Throttle = {"raw": "0x10", "flags": []}
    assert decode_throttled(0x10) == expected


# ── vcgencmd output parsing ──────────────────────────────────────────────────


def test_parse_throttled() -> None:
    assert parse_throttled("throttled=0x50005\n") == decode_throttled(0x50005)


@pytest.mark.parametrize("out", ["", "throttled=", "throttled=zz", "garbage"])
def test_parse_throttled_unparseable_is_none(out: str) -> None:
    assert parse_throttled(out) is None


def test_parse_temp() -> None:
    assert parse_temp("temp=48.3'C\n") == 48.3


@pytest.mark.parametrize("out", ["", "temp='C", "temp=hot'C", "48.3"])
def test_parse_temp_unparseable_is_none(out: str) -> None:
    assert parse_temp(out) is None


# ── network pick ─────────────────────────────────────────────────────────────


class Addr(NamedTuple):
    """The slice of psutil's snicaddr that pick_network reads."""

    family: int
    address: str
    netmask: str | None


def _addrs(**ifaces: Sequence[Addr]) -> dict[str, Sequence[Addr]]:
    return dict(ifaces)


def test_network_first_non_loopback_ipv4() -> None:
    addrs = _addrs(
        lo=[Addr(socket.AF_INET, "127.0.0.1", "255.0.0.0")],
        wlan0=[
            Addr(socket.AF_INET6, "fe80::1", None),
            Addr(socket.AF_INET, "192.168.1.42", "255.255.255.0"),
        ],
        eth1=[Addr(socket.AF_INET, "10.0.0.5", "255.0.0.0")],
    )
    assert pick_network(addrs) == {
        "iface": "wlan0",
        "ip": "192.168.1.42",
        "netmask": "255.255.255.0",
        "prefix": 24,
    }


def test_network_only_loopback_is_none() -> None:
    addrs = _addrs(lo=[Addr(socket.AF_INET, "127.0.0.1", "255.0.0.0")])
    assert pick_network(addrs) is None


def test_network_skips_link_local() -> None:
    addrs = _addrs(
        eth0=[Addr(socket.AF_INET, "169.254.3.4", "255.255.0.0")],
        wlan0=[Addr(socket.AF_INET, "192.168.1.42", "255.255.255.0")],
    )
    assert pick_network(addrs) == {
        "iface": "wlan0",
        "ip": "192.168.1.42",
        "netmask": "255.255.255.0",
        "prefix": 24,
    }


def test_network_missing_or_bad_netmask_keeps_the_address() -> None:
    addrs = _addrs(wlan0=[Addr(socket.AF_INET, "192.168.1.42", None)])
    assert pick_network(addrs) == {
        "iface": "wlan0",
        "ip": "192.168.1.42",
        "netmask": None,
        "prefix": None,
    }


# ── collect(): fail-soft per field ───────────────────────────────────────────


def _no_vcgencmd(*_a: Any, **_k: Any) -> subprocess.CompletedProcess[str]:
    raise FileNotFoundError("vcgencmd")


def test_collect_without_vcgencmd_reports_pi_fields_unavailable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(subprocess, "run", _no_vcgencmd)
    got = stats.collect()
    assert got["temp_c"] is None
    assert got["throttle"] is None
    # The psutil families still answer on this (any) dev box.
    assert got["cpu_percent"] is not None
    assert got["memory"] is not None
    assert got["uptime_s"] is not None


def test_collect_vcgencmd_nonzero_exit_is_unavailable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def failing(args: Sequence[str], **_k: Any) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess(args, 255, "", "VCHI init failed")

    monkeypatch.setattr(subprocess, "run", failing)
    got = stats.collect()
    assert got["temp_c"] is None
    assert got["throttle"] is None


def test_collect_on_pi_reads_vcgencmd(monkeypatch: pytest.MonkeyPatch) -> None:
    replies = {"measure_temp": "temp=48.3'C\n", "get_throttled": "throttled=0x0\n"}

    def vcgencmd(args: Sequence[str], **_k: Any) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess(args, 0, replies[args[1]], "")

    monkeypatch.setattr(subprocess, "run", vcgencmd)
    got = stats.collect()
    assert got["temp_c"] == 48.3
    assert got["throttle"] == decode_throttled(0x0)


def test_collect_never_raises_with_every_probe_broken(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def boom(*_a: Any, **_k: Any) -> Any:
        raise RuntimeError("probe failed")

    for name in (
        "cpu_percent",
        "virtual_memory",
        "disk_usage",
        "boot_time",
        "net_if_addrs",
    ):
        monkeypatch.setattr(psutil, name, boom)
    monkeypatch.setattr(socket, "gethostname", boom)
    monkeypatch.setattr(subprocess, "run", boom)
    assert stats.collect() == {
        "cpu_percent": None,
        "memory": None,
        "disk": None,
        "uptime_s": None,
        "host": None,
        "temp_c": None,
        "throttle": None,
        "network": None,
    }


def test_collect_usage_is_used_over_total(monkeypatch: pytest.MonkeyPatch) -> None:
    class Mem(NamedTuple):
        total: int
        available: int

    class Disk(NamedTuple):
        total: int
        used: int

    monkeypatch.setattr(psutil, "virtual_memory", lambda: Mem(4000, 2500))
    monkeypatch.setattr(psutil, "disk_usage", lambda _p: Disk(29000, 4100))
    monkeypatch.setattr(psutil, "boot_time", lambda: 1000.0)
    monkeypatch.setattr(time, "time", lambda: 1000.0 + 31_560.9)
    monkeypatch.setattr(subprocess, "run", _no_vcgencmd)
    got = stats.collect()
    assert got["memory"] == {"used": 1500, "total": 4000}
    assert got["disk"] == {"used": 4100, "total": 29000}
    assert got["uptime_s"] == 31_560


# ── GET /api/admin/stats ─────────────────────────────────────────────────────


def test_stats_route_serves_every_family_uncached(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(subprocess, "run", _no_vcgencmd)
    resp = TestClient(app).get("/api/admin/stats")
    assert resp.status_code == 200
    assert resp.headers["cache-control"] == "no-store"
    assert set(resp.json()) == {
        "cpu_percent",
        "memory",
        "disk",
        "uptime_s",
        "host",
        "temp_c",
        "throttle",
        "network",
    }


def test_stats_route_degrades_to_all_unavailable_not_500(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def boom() -> stats.Stats:
        raise RuntimeError("unexpected")

    monkeypatch.setattr(stats, "collect", boom)
    resp = TestClient(app).get("/api/admin/stats")
    assert resp.status_code == 200
    assert all(v is None for v in resp.json().values())


# ── the throttle vocabulary, end to end ─────────────────────────────────────


def test_js_contract_throttle_flags_match_python() -> None:
    # The frontend's label table is typed by contract.js's ThrottleFlag, so tsc
    # catches a missing label; this catches the two vocabularies drifting.
    contract = (Path(__file__).parent.parent / "static/core/contract.js").read_text()
    m = re.search(r"@typedef \{([^}]*)\} ThrottleFlag", contract)
    assert m is not None
    js = {s.strip().strip('"') for s in m[1].split("|")}
    assert js == set(get_args(stats.ThrottleFlag))
