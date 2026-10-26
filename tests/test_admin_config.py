"""The admin config API: GET/POST /api/admin/config, plus the restart helper.

GET exposes exactly the three presentation knobs (never the secret or any other
setting); POST validates staged values against the on-disk option sets, writes
only the diff to .env, and schedules the detached restart. Every test repoints
the .env path at tmp_path and fakes the restart, so nothing here can touch the
real .env or a real systemd.
"""

from __future__ import annotations

import subprocess
from collections.abc import Sequence
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from app import main, service
from app.config import settings
from app.main import _available_slugs, _available_themes, _BOOT_ID, app

_ENV = "PROTON_ICS_URL=https://x.test/cal.ics?k=v#f\nLAYOUT=classic\nTHEME=\n"


@pytest.fixture
def env_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    path = tmp_path / ".env"
    path.write_text(_ENV, encoding="utf-8")
    monkeypatch.setattr(main, "_ENV_FILE", path)
    monkeypatch.setattr(settings, "layout", "classic")
    monkeypatch.setattr(settings, "theme", "")
    monkeypatch.setattr(settings, "icon_pack", "weather-icons")
    return path


@pytest.fixture
def restarts(monkeypatch: pytest.MonkeyPatch) -> list[int]:
    """Records each restart request instead of shelling out to systemd-run."""
    calls: list[int] = []

    def fake() -> bool:
        calls.append(1)
        return True

    monkeypatch.setattr(service, "restart_dashboard", fake)
    return calls


def _post(body: object) -> tuple[int, Any]:
    resp = TestClient(app).post("/api/admin/config", json=body)
    return resp.status_code, resp.json()


# ── GET ──────────────────────────────────────────────────────────────────────


def test_get_returns_exactly_the_three_knobs(env_file: Path) -> None:
    resp = TestClient(app).get("/api/admin/config")
    assert resp.status_code == 200
    body = resp.json()
    assert set(body) == {"layout", "theme", "icon_pack"}
    for knob in body.values():
        assert set(knob) == {"current", "options"}
    assert body["layout"] == {
        "current": "classic",
        "options": _available_slugs("layouts"),
    }
    assert body["theme"]["current"] == ""
    assert body["icon_pack"]["current"] == "weather-icons"
    assert body["icon_pack"]["options"] == _available_slugs("packs")


def test_get_never_serializes_the_secret(
    env_file: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(settings, "proton_ics_url", "https://secret.test/ics")
    text = TestClient(app).get("/api/admin/config").text
    assert "secret.test" not in text
    assert "proton" not in text.lower()


def test_theme_options_are_the_builtin_palette_plus_each_stylesheet() -> None:
    themes = _available_themes()
    assert themes[0] == ""
    assert themes[1:] == sorted(
        p.stem for p in (main._static_dir / "themes").glob("*.css")
    )
    assert "nord" in themes


def test_get_reports_the_effective_value_for_an_unresolvable_setting(
    env_file: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # A bad value renders the built-in default, so that is what is "live".
    monkeypatch.setattr(settings, "layout", "bogus")
    monkeypatch.setattr(settings, "theme", "nope")
    monkeypatch.setattr(settings, "icon_pack", "../etc")
    body = TestClient(app).get("/api/admin/config").json()
    assert body["layout"]["current"] == "classic"
    assert body["theme"]["current"] == ""
    assert body["icon_pack"]["current"] == "weather-icons"


def test_get_folds_case_and_space_like_the_asset_routes(
    env_file: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(settings, "layout", " HUD ")
    assert TestClient(app).get("/api/admin/config").json()["layout"]["current"] == "hud"


# ── POST ─────────────────────────────────────────────────────────────────────


def test_post_writes_the_diff_and_schedules_a_restart(
    env_file: Path, restarts: list[int]
) -> None:
    status, body = _post({"layout": "hud", "theme": "nord"})
    assert status == 200
    assert body == {"restarted": True, "boot": _BOOT_ID}
    assert restarts == [1]
    text = env_file.read_text(encoding="utf-8")
    assert "LAYOUT=hud\n" in text
    assert "THEME=nord\n" in text
    assert text.startswith("PROTON_ICS_URL=https://x.test/cal.ics?k=v#f\n")


def test_post_writes_only_changed_keys(env_file: Path, restarts: list[int]) -> None:
    # icon_pack is staged at its current value, so it is not a change and must
    # not be appended to .env.
    status, _ = _post({"theme": "nord", "icon_pack": "weather-icons"})
    assert status == 200
    assert "ICON_PACK" not in env_file.read_text(encoding="utf-8")


def test_post_can_return_to_the_builtin_palette(
    env_file: Path, restarts: list[int], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(settings, "theme", "nord")
    status, _ = _post({"theme": ""})
    assert status == 200
    assert "THEME=\n" in env_file.read_text(encoding="utf-8")


@pytest.mark.parametrize("body", [{}, {"layout": "classic"}, {"theme": ""}])
def test_post_noop_writes_nothing_and_does_not_restart(
    env_file: Path, restarts: list[int], body: dict[str, str]
) -> None:
    before = env_file.stat().st_mtime_ns
    assert _post(body) == (200, {"restarted": False})
    assert restarts == []
    assert env_file.read_text(encoding="utf-8") == _ENV
    assert env_file.stat().st_mtime_ns == before


@pytest.mark.parametrize(
    "body",
    [
        {"layout": "bogus"},
        {"layout": "../classic"},
        {"theme": "nord\nPROTON_ICS_URL=evil"},
        {"layout": "HUD"},  # options are exact, not case-folded
        {"layout": "hud", "theme": "nope"},  # one bad value rejects the whole apply
    ],
)
def test_post_rejects_an_unknown_value_without_writing(
    env_file: Path, restarts: list[int], body: dict[str, str]
) -> None:
    status, resp = _post(body)
    assert status == 400
    assert "detail" in resp
    assert restarts == []
    assert env_file.read_text(encoding="utf-8") == _ENV


def test_post_rejects_an_unknown_key(env_file: Path, restarts: list[int]) -> None:
    resp = TestClient(app).post("/api/admin/config", json={"proton_ics_url": "x"})
    assert resp.status_code == 422
    assert restarts == []
    assert env_file.read_text(encoding="utf-8") == _ENV


def test_post_rejects_a_non_json_body(env_file: Path, restarts: list[int]) -> None:
    # A cross-origin page can only send a "simple" request (text/plain, no
    # preflight); it must not be parsed as a config update.
    resp = TestClient(app).post(
        "/api/admin/config",
        content='{"layout": "hud"}',
        headers={"Content-Type": "text/plain"},
    )
    assert resp.status_code == 422
    assert restarts == []
    assert env_file.read_text(encoding="utf-8") == _ENV


def test_post_creates_env_when_absent(
    env_file: Path, restarts: list[int]
) -> None:
    env_file.unlink()
    status, _ = _post({"layout": "hud"})
    assert status == 200
    assert env_file.read_text(encoding="utf-8") == "LAYOUT=hud\n"


def test_post_preserves_the_env_file_mode(
    env_file: Path, restarts: list[int]
) -> None:
    env_file.chmod(0o600)
    _post({"layout": "hud"})
    assert env_file.stat().st_mode & 0o777 == 0o600


def test_post_write_failure_is_a_500_and_skips_the_restart(
    env_file: Path, restarts: list[int], monkeypatch: pytest.MonkeyPatch
) -> None:
    def boom(path: Path, text: str) -> None:
        raise OSError("read-only filesystem")

    monkeypatch.setattr(main, "_write_atomic", boom)
    status, resp = _post({"layout": "hud"})
    assert status == 500
    assert "detail" in resp
    assert restarts == []
    assert env_file.read_text(encoding="utf-8") == _ENV


def test_post_restart_failure_is_a_500_but_keeps_the_write(
    env_file: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(service, "restart_dashboard", lambda: False)
    status, resp = _post({"layout": "hud"})
    assert status == 500
    assert "restart" in resp["detail"]
    assert "LAYOUT=hud\n" in env_file.read_text(encoding="utf-8")


def test_healthz_carries_the_boot_id() -> None:
    # The client waits for this to change to know the restart actually happened.
    assert TestClient(app).get("/healthz").json() == {"status": "ok", "boot": _BOOT_ID}


# ── restart helper ───────────────────────────────────────────────────────────


class _FakeRun:
    def __init__(self, returncode: int = 0, exc: Exception | None = None) -> None:
        self.returncode = returncode
        self.exc = exc
        self.cmds: list[Sequence[str]] = []

    def __call__(self, cmd: Sequence[str], **kwargs: Any) -> subprocess.CompletedProcess[str]:
        self.cmds.append(cmd)
        if self.exc is not None:
            raise self.exc
        return subprocess.CompletedProcess(cmd, self.returncode, "", "boom")


def test_restart_schedules_a_detached_transient_unit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    run = _FakeRun()
    monkeypatch.setattr(subprocess, "run", run)
    assert service.restart_dashboard() is True
    assert run.cmds == [
        (
            "systemd-run",
            "--user",
            "--collect",
            "--on-active=1s",
            "--timer-property=AccuracySec=100ms",
            "systemctl",
            "--user",
            "restart",
            "pi-dashboard.service",
        )
    ]


@pytest.mark.parametrize(
    "run",
    [
        _FakeRun(returncode=1),
        _FakeRun(exc=FileNotFoundError("systemd-run")),  # the dev Mac
        _FakeRun(exc=subprocess.TimeoutExpired("systemd-run", 10)),
    ],
)
def test_restart_fails_soft(monkeypatch: pytest.MonkeyPatch, run: _FakeRun) -> None:
    monkeypatch.setattr(subprocess, "run", run)
    assert service.restart_dashboard() is False
