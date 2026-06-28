"""Weather source — Open-Meteo.

Phase 1 stub. Phase 3 (thin vertical slice) implements the real fetch:
blocking `requests` call offloaded via `asyncio.to_thread` (spec §5), 4-day
forecast (forecast_days=5, daily[1:5]), fields incl. wind/humidity/sunrise/sunset.
"""

from __future__ import annotations

from typing import Any


async def get_weather() -> dict[str, Any]:
    """Return current + 4-day forecast. (stub)"""
    raise NotImplementedError("weather.get_weather — implemented in Phase 3")
