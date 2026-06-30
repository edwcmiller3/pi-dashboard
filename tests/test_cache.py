"""Phase 3 — JSON cache round-trip + missing-key behavior."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import pytest

from app import cache
from app.config import settings


def test_read_missing_key_returns_none(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(settings, "cache_dir", str(tmp_path))
    assert cache.read("never-written") is None


def test_write_then_read_roundtrips(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(settings, "cache_dir", str(tmp_path))
    value: dict[str, Any] = {"a": [1, 2, 3], "b": "x", "nested": {"ok": True}}
    cache.write("doc", value)
    assert cache.read("doc") == value


def test_write_creates_cache_dir(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    nested = tmp_path / "var" / "deep"
    monkeypatch.setattr(settings, "cache_dir", str(nested))
    cache.write("doc", {"ok": True})
    assert (nested / "doc.json").exists()


def test_write_leaves_no_tmp_file(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    # The atomic temp file must be renamed away, not left behind.
    monkeypatch.setattr(settings, "cache_dir", str(tmp_path))
    cache.write("doc", {"ok": True})
    assert list(tmp_path.glob("*.tmp")) == []


# ── Phase 6 — corrupt/unreadable cache is non-fatal (degrades like a cold cache)


def test_read_corrupt_json_returns_none(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    # A truncated/garbage cache file (realistically only power-loss mid-write,
    # which the atomic os.replace already rules out for torn reads) must degrade
    # to a cold cache (None -> 503), NOT bubble a JSONDecodeError to a 500.
    monkeypatch.setattr(settings, "cache_dir", str(tmp_path))
    (tmp_path / "doc.json").write_text('{"weather": {"ok": tru', encoding="utf-8")
    assert cache.read("doc") is None


def test_read_empty_file_returns_none(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    # An empty file also fails json.load — treat it like a cold cache.
    monkeypatch.setattr(settings, "cache_dir", str(tmp_path))
    (tmp_path / "doc.json").write_text("", encoding="utf-8")
    assert cache.read("doc") is None


def test_write_fsyncs_for_power_loss_durability(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    # The atomic os.replace is torn-read-safe but NOT power-loss-durable on its
    # own; the data (and the rename) must be fsync'd so a crash can't lose or
    # corrupt the last-good doc. Assert fsync is actually called.
    monkeypatch.setattr(settings, "cache_dir", str(tmp_path))
    calls: list[int] = []
    real_fsync = os.fsync

    def counting_fsync(fd: int) -> None:
        calls.append(fd)
        real_fsync(fd)

    monkeypatch.setattr(os, "fsync", counting_fsync)
    cache.write("doc", {"ok": True})
    assert calls  # at least the file (and, where supported, its directory)
    assert cache.read("doc") == {"ok": True}
