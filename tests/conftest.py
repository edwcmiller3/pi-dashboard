"""Shared pytest fixtures.

The autouse `_tmp_cache` fixture redirects the JSON cache at `settings.cache_dir`
to a per-test `tmp_path` for EVERY test. That kills the ~20 duplicated
`monkeypatch.setattr(settings, "cache_dir", str(tmp_path))` lines that used to
open each cache-touching test AND guarantees no test can ever read or write the
real `var/` dir (a test that forgot the redirect used to be one edit away from
clobbering a live last-good doc). Tests that need a differently-shaped cache dir
(e.g. a not-yet-created nested path) still override `cache_dir` themselves — the
autouse fixture just sets a safe default first.
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest

from app.config import settings


@pytest.fixture(autouse=True)
def _tmp_cache(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """Point the cache at an isolated tmp dir for every test (see module docs)."""
    monkeypatch.setattr(settings, "cache_dir", str(tmp_path))


@pytest.fixture
def clock_synced(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Iterator[Path]:
    """Make `main._clock_synced()` report True: the timesyncd runtime dir exists
    (its parent, `tmp_path`) and the `synchronized` marker is present. Yields the
    marker path so a test can flip the state (e.g. unlink it) if needed."""
    from app import main

    marker = tmp_path / "synchronized"
    marker.write_text("", encoding="utf-8")
    monkeypatch.setattr(main, "_TIMESYNC_MARKER", marker)
    yield marker
