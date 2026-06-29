"""Cache interface — JSON files on disk. Deliberately simple: no Redis, no
SQLite, no store migration planned (decided 2026-06-29). The cache holds two
regenerable blobs for one local process, so a cache server / embedded DB would
be pure overhead. The small read/write seam stays only to keep the loop and
route decoupled and the tests clean.

The handoff between the background refresh loop (writer) and the `/api/data`
route (reader). Writes go through a temp file + `os.replace` so a concurrent
reader can never observe a half-written file (torn-read-safe). TTL handling,
corrupt-file tolerance, and power-loss durability (fsync) land in Phase 6.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from app.config import settings


def _cache_path(key: str) -> Path:
    return Path(settings.cache_dir) / f"{key}.json"


def read(key: str) -> Any | None:
    """Return the cached value for `key`, or None if it hasn't been written yet."""
    try:
        with _cache_path(key).open(encoding="utf-8") as fh:
            return json.load(fh)
    except FileNotFoundError:
        return None


def write(key: str, value: Any) -> None:
    """Persist `value` under `key` as JSON, atomically (temp file + os.replace)."""
    path = _cache_path(key)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    with tmp.open("w", encoding="utf-8") as fh:
        json.dump(value, fh)
    os.replace(tmp, path)
