"""JSON-file cache: the handoff between the refresh loop (writer) and the
`/api/data` route (reader).

Deliberately just files - it holds regenerable blobs for one local process, so a
cache server or embedded DB would be pure overhead.
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
    """The cached value, or None if absent or unreadable - a corrupt file is a
    cold cache (the route returns 503), never a 500."""
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
    """Write atomically (temp file + `os.replace`, so readers never see a partial
    file) and durably (data and directory fsync'd, so a power cut can't lose the
    last-good doc)."""
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
    """Best-effort: a platform that disallows directory fsync is a no-op (the
    file data is already fsync'd, which is the load-bearing half)."""
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
