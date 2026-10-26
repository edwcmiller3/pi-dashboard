"""Shared HTTP session factory for the outbound source fetches.

A long-lived session reuses the TCP/TLS connection across refresh ticks, which
matters on flaky Wi-Fi where connection setup is where failures cluster; a
small bounded retry rides out a dropped packet without losing a whole tick.

Each source owns a module-level session. Fetches are serialized under
`_refresh_lock`, so no session is used by two threads at once.
"""

from __future__ import annotations

from typing import Final

from requests import Session
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

# raise_on_status=False leaves the final response for the caller's
# `raise_for_status()`, so the error path stays in one place.
_RETRY: Final = Retry(
    total=2,
    backoff_factor=0.3,
    status_forcelist=(429, 500, 502, 503, 504),
    allowed_methods=frozenset({"GET"}),
    raise_on_status=False,
)


def build_session() -> Session:
    session = Session()
    adapter = HTTPAdapter(max_retries=_RETRY)
    session.mount("https://", adapter)
    session.mount("http://", adapter)
    return session
