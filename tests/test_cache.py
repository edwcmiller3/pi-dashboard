"""Phase 3 — JSON cache round-trip + missing-key behavior."""

from __future__ import annotations

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
