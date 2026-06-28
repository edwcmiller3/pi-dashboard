"""Cache interface — JSON-on-disk now, SQLite-swappable later.

Phase 1 stub: defines the shape so sources can target a stable interface.
Real read/write + TTL handling lands with the freshness hardening (Phase 6).
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from app.config import settings


def _cache_path(key: str) -> Path:
    return Path(settings.cache_dir) / f"{key}.json"


def read(key: str) -> Any | None:
    """Return cached value for `key`, or None if absent/stale. (stub)"""
    raise NotImplementedError("cache.read — implemented in Phase 6")


def write(key: str, value: Any) -> None:
    """Persist `value` under `key`. (stub)"""
    raise NotImplementedError("cache.write — implemented in Phase 6")
