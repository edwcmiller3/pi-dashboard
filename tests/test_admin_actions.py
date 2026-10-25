"""The admin device actions: POST /api/admin/restart, GET + POST /api/admin/reboot,
and the logind helpers behind reboot.

Every route test fakes the service helpers and every helper test fakes
subprocess.run, so nothing here can restart a real service or reboot the host.
"""

from __future__ import annotations

import subprocess
from collections.abc import Sequence
from typing import Any

import pytest
from fastapi.testclient import TestClient

from app import service
from app.main import _BOOT_ID, app
from app.service import RebootOutcome

_LOGIND = (
    "busctl",
    "--allow-interactive-authorization=no",
    "call",
    "org.freedesktop.login1",
    "/org/freedesktop/login1",
    "org.freedesktop.login1.Manager",
)
_DENIED = "Call failed: Interactive authentication required.\n"


class _FakeRun:
    def __init__(
        self,
        returncode: int = 0,
        stdout: str = "",
        stderr: str = "",
        exc: Exception | None = None,
    ) -> None:
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr
        self.exc = exc
        self.cmds: list[Sequence[str]] = []

    def __call__(
        self, cmd: Sequence[str], **kwargs: Any
    ) -> subprocess.CompletedProcess[str]:
        self.cmds.append(cmd)
        if self.exc is not None:
            raise self.exc
        return subprocess.CompletedProcess(
            cmd, self.returncode, self.stdout, self.stderr
        )


def _client() -> TestClient:
    return TestClient(app)


@pytest.fixture
def fired(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    """Records each restart/reboot request instead of touching systemd/logind."""
    calls: list[str] = []

    def restart() -> bool:
        calls.append("restart")
        return True

    def reboot() -> RebootOutcome:
        calls.append("reboot")
        return "rebooting"

    monkeypatch.setattr(service, "restart_dashboard", restart)
    monkeypatch.setattr(service, "reboot", reboot)
    return calls


# ── POST /api/admin/restart ──────────────────────────────────────────────────


def test_restart_schedules_the_restart_and_echoes_the_boot_id(
    fired: list[str],
) -> None:
    resp = _client().post("/api/admin/restart", json={})
    assert resp.status_code == 200
    assert resp.json() == {"restarted": True, "boot": _BOOT_ID}
    assert fired == ["restart"]


def test_restart_failure_is_a_500(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(service, "restart_dashboard", lambda: False)
    resp = _client().post("/api/admin/restart", json={})
    assert resp.status_code == 500
    assert "restart" in resp.json()["detail"]


@pytest.mark.parametrize("path", ["/api/admin/restart", "/api/admin/reboot"])
def test_actions_reject_a_non_json_body(fired: list[str], path: str) -> None:
    # A cross-origin "simple" POST can't carry application/json, so requiring a
    # JSON body keeps another page in the kiosk browser from firing these.
    resp = _client().post(path, content="{}", headers={"Content-Type": "text/plain"})
    assert resp.status_code == 422
    assert fired == []


@pytest.mark.parametrize("path", ["/api/admin/restart", "/api/admin/reboot"])
def test_actions_reject_unknown_keys(fired: list[str], path: str) -> None:
    assert _client().post(path, json={"force": True}).status_code == 422
    assert fired == []


# ── GET + POST /api/admin/reboot ─────────────────────────────────────────────


@pytest.mark.parametrize("available", [True, False])
def test_reboot_availability_is_served_uncached(
    monkeypatch: pytest.MonkeyPatch, available: bool
) -> None:
    monkeypatch.setattr(service, "reboot_available", lambda: available)
    resp = _client().get("/api/admin/reboot")
    assert resp.status_code == 200
    assert resp.json() == {"available": available}
    assert resp.headers["cache-control"] == "no-store"


@pytest.mark.parametrize(
    ("outcome", "status"),
    [("rebooting", 200), ("unavailable", 503), ("failed", 500)],
)
def test_reboot_maps_each_outcome_to_a_status(
    monkeypatch: pytest.MonkeyPatch, outcome: RebootOutcome, status: int
) -> None:
    monkeypatch.setattr(service, "reboot", lambda: outcome)
    resp = _client().post("/api/admin/reboot", json={})
    assert resp.status_code == status
    if status == 200:
        assert resp.json() == {"rebooting": True}
    else:
        # Never a false "rebooting..." - the client gets a reason instead.
        assert "rebooting" not in resp.json()
        assert resp.json()["detail"]


# ── logind helpers ───────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    ("stdout", "answer"),
    [
        ('s "yes"\n', "yes"),
        ('s "challenge"\n', "challenge"),
        ('s "no"\n', "no"),
        ('s "na"\n', "na"),
        ("", None),
        ("garbage", None),
    ],
)
def test_parse_can_reboot(stdout: str, answer: str | None) -> None:
    assert service.parse_can_reboot(stdout) == answer


def test_can_reboot_asks_logind_non_interactively(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    run = _FakeRun(stdout='s "yes"\n')
    monkeypatch.setattr(subprocess, "run", run)
    assert service.can_reboot() == "yes"
    assert run.cmds == [(*_LOGIND, "CanReboot")]


@pytest.mark.parametrize(
    ("run", "available"),
    [
        (_FakeRun(stdout='s "yes"\n'), True),
        # No polkit rule: logind would prompt for a password, which a kiosk can't.
        (_FakeRun(stdout='s "challenge"\n'), False),
        (_FakeRun(stdout='s "no"\n'), False),
        (_FakeRun(returncode=1, stderr="boom"), False),
        (_FakeRun(exc=FileNotFoundError("busctl")), False),  # the dev Mac
        (_FakeRun(exc=subprocess.TimeoutExpired("busctl", 5)), False),
    ],
)
def test_reboot_available_only_on_yes(
    monkeypatch: pytest.MonkeyPatch, run: _FakeRun, available: bool
) -> None:
    monkeypatch.setattr(subprocess, "run", run)
    assert service.reboot_available() is available


def test_reboot_calls_logind_reboot_without_interactive_auth(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    run = _FakeRun()
    monkeypatch.setattr(subprocess, "run", run)
    assert service.reboot() == "rebooting"
    assert run.cmds == [(*_LOGIND, "Reboot", "b", "false")]


@pytest.mark.parametrize(
    ("run", "outcome"),
    [
        (_FakeRun(returncode=1, stderr=_DENIED), "unavailable"),
        (_FakeRun(returncode=1, stderr="Call failed: Access denied\n"), "unavailable"),
        (_FakeRun(exc=FileNotFoundError("busctl")), "unavailable"),
        (_FakeRun(returncode=1, stderr="Call failed: something else\n"), "failed"),
        (_FakeRun(exc=subprocess.TimeoutExpired("busctl", 5)), "failed"),
    ],
)
def test_reboot_fails_soft(
    monkeypatch: pytest.MonkeyPatch, run: _FakeRun, outcome: RebootOutcome
) -> None:
    monkeypatch.setattr(subprocess, "run", run)
    assert service.reboot() == outcome
