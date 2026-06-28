"""Calendar source — Proton ICS (Full-view URL).

Phase 1 stub. Phase 5 implements: fetch the ICS via `requests` (offloaded),
parse with `icalendar`, expand recurrences with `recurring-ical-events`
(honoring EXDATE on the master — confirmed 0.D1). URL is secret + PII-bearing.
"""

from __future__ import annotations

from typing import Any


async def get_events() -> list[dict[str, Any]]:
    """Return upcoming agenda events. (stub)"""
    raise NotImplementedError("calendar.get_events — implemented in Phase 5")
