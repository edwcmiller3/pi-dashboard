"""Shared HTTP session factory for the outbound source fetches.

A long-lived `requests.Session` (vs. a fresh `requests.get` per call) reuses the
pooled TCP/TLS connection across refresh ticks — on a wall-mounted kiosk that's
one handshake per host instead of one every 15 min, which matters most on flaky
Wi-Fi where connection setup is exactly where transient failures cluster. A
small bounded `Retry` on idempotent GETs rides out a single dropped packet
without burning a whole refresh tick.

Each source owns its own module-level session (see `weather`/`calendar`). The
refresh loop serializes every fetch under `_refresh_lock` and awaits the two
sources in turn, so a given session is only ever touched by one worker thread at
a time — well within what `requests.Session` supports.
"""

from __future__ import annotations

from typing import Final

from requests import Session
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

# Idempotent GETs only. total=2 → up to three attempts; backoff 0.3s → ~0.3s,
# 0.6s between them. raise_on_status=False leaves the final response for the
# caller's `raise_for_status()` so the existing error path is unchanged.
_RETRY: Final = Retry(
    total=2,
    backoff_factor=0.3,
    status_forcelist=(429, 500, 502, 503, 504),
    allowed_methods=frozenset({"GET"}),
    raise_on_status=False,
)


def build_session() -> Session:
    """A `requests.Session` with connection pooling and a bounded transient-retry
    on idempotent GETs."""
    session = Session()
    adapter = HTTPAdapter(max_retries=_RETRY)
    session.mount("https://", adapter)
    session.mount("http://", adapter)
    return session
