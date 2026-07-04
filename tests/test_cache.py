"""JSON cache round-trip + missing-key behavior.

`cache_dir` is redirected to a per-test tmp dir by the autouse `_tmp_cache`
fixture (see conftest), so these tests write only under `tmp_path`.
"""

from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Any

import pytest

from app import cache
from app.config import settings


def test_read_missing_key_returns_none() -> None:
    assert cache.read("never-written") is None


def test_write_then_read_roundtrips() -> None:
    value: dict[str, Any] = {"a": [1, 2, 3], "b": "x", "nested": {"ok": True}}
    cache.write("doc", value)
    assert cache.read("doc") == value


def test_write_creates_cache_dir(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    # Override the autouse redirect with a not-yet-created nested path.
    nested = tmp_path / "var" / "deep"
    monkeypatch.setattr(settings, "cache_dir", str(nested))
    cache.write("doc", {"ok": True})
    assert (nested / "doc.json").exists()


def test_write_leaves_no_tmp_file(tmp_path: Path) -> None:
    # The atomic temp file must be renamed away, not left behind.
    cache.write("doc", {"ok": True})
    assert list(tmp_path.glob("*.tmp")) == []


# ── corrupt/unreadable cache is non-fatal (degrades like a cold cache) ───────


def test_read_corrupt_json_returns_none(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    # A truncated/garbage cache file (realistically only power-loss mid-write,
    # which the atomic os.replace already rules out for torn reads) must degrade
    # to a cold cache (None -> 503), NOT bubble a JSONDecodeError to a 500 — and
    # it must WARN, since that log is the only signal an operator gets on the Pi.
    (tmp_path / "doc.json").write_text('{"weather": {"ok": tru', encoding="utf-8")
    with caplog.at_level(logging.WARNING, logger="pi_dashboard.cache"):
        assert cache.read("doc") is None
    assert caplog.records  # the degrade-to-cold-cache warning actually fired
    assert "doc" in caplog.text


def test_read_empty_file_returns_none(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    # An empty file also fails json.load — treat it like a cold cache, and warn.
    (tmp_path / "doc.json").write_text("", encoding="utf-8")
    with caplog.at_level(logging.WARNING, logger="pi_dashboard.cache"):
        assert cache.read("doc") is None
    assert caplog.records


def test_write_fsyncs_file_and_dir_for_power_loss_durability(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # The atomic os.replace is torn-read-safe but NOT power-loss-durable on its
    # own; BOTH the data file AND the containing directory must be fsync'd so a
    # crash can't lose or corrupt the last-good doc, or lose the rename. Assert
    # both fsyncs happen — a regression dropping the directory fsync would still
    # leave the file fsync behind and slip past a mere "fsync was called" check.
    calls: list[int] = []
    real_fsync = os.fsync

    def counting_fsync(fd: int) -> None:
        calls.append(fd)
        real_fsync(fd)

    monkeypatch.setattr(os, "fsync", counting_fsync)
    cache.write("doc", {"ok": True})
    # file fd + directory fd = two fsyncs (the fd integers may repeat: the file
    # is closed before the dir is opened, so the OS can reuse the number).
    assert len(calls) >= 2
    assert cache.read("doc") == {"ok": True}
