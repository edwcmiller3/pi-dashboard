"""Cache interface — JSON files on disk. Deliberately simple: no Redis, no
SQLite, no store migration planned (decided 2026-06-29). The cache holds two
regenerable blobs for one local process, so a cache server / embedded DB would
be pure overhead. The small read/write seam stays only to keep the loop and
route decoupled and the tests clean.

The handoff between the background refresh loop (writer) and the `/api/data`
route (reader). Writes go through a temp file + `os.replace` so a concurrent
reader can never observe a half-written file (torn-read-safe), and the data +
the rename are `fsync`'d so a power loss can't lose or corrupt the last-good
doc (durability boundary). A corrupt/unreadable file degrades to a cold cache
(`None`) rather than bubbling out of `/api/data` as a 500.
"""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path
from typing import Any

from app.config import settings

log = logging.getLogger("pi_dashboard.cache")


def _cache_path(key: str) -> Path:
    return Path(settings.cache_dir) / f"{key}.json"


def read(key: str) -> Any | None:
    """Return the cached value for `key`, or None if it's absent or unreadable.

    A missing file is the normal cold-cache case. A corrupt/empty file (the only
    realistic trigger is a power loss mid-write — the atomic `os.replace` rules
    out torn reads) is treated the same: degrade to `None` (the route then
    returns 503 and the frontend shows last-good / placeholders), never a 500.
    """
    try:
        with _cache_path(key).open(encoding="utf-8") as fh:
            return json.load(fh)
    except FileNotFoundError:
        return None
    except (json.JSONDecodeError, UnicodeDecodeError, OSError) as exc:
        log.warning(
            "cache read for %r failed (%s); treating as cold cache",
            key,
            type(exc).__name__,
        )
        return None


def write(key: str, value: Any) -> None:
    """Persist `value` under `key` as JSON, atomically and durably.

    Atomic: written to a temp file then `os.replace`d into place (a reader never
    sees a half-written file). Durable: the temp file's data is `fsync`'d before
    the rename, and the directory is `fsync`'d after, so neither the contents nor
    the rename can be lost to a power cut mid-write.
    """
    path = _cache_path(key)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    with tmp.open("w", encoding="utf-8") as fh:
        json.dump(value, fh)
        fh.flush()
        os.fsync(fh.fileno())
    os.replace(tmp, path)
    _fsync_dir(path.parent)


def _fsync_dir(directory: Path) -> None:
    """`fsync` a directory so a rename into it survives power loss. POSIX-only;
    a platform/filesystem that disallows it is a best-effort no-op (the file
    data is already fsync'd, which is the load-bearing half)."""
    try:
        fd = os.open(directory, os.O_RDONLY)
    except OSError:
        return
    try:
        os.fsync(fd)
    except OSError:
        pass
    finally:
        os.close(fd)
