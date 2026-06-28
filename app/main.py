"""FastAPI application entrypoint.

Phase 1 stub: a runnable app that satisfies the exit criterion
(`uv run uvicorn app.main:app` starts and serves). Phase 2 fills static/,
Phases 3-6 wire the live data sources.
"""

from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

app = FastAPI(title="pi-dashboard", version="0.1.0")


@app.get("/healthz")
def healthz() -> JSONResponse:
    """Liveness probe — also the thing the Phase-1 exit criterion hits."""
    return JSONResponse({"status": "ok"})


# Serve the static dashboard (Phase 2 fills static/). html=True serves index.html
# at "/". Mounted last so /healthz and future /api routes take precedence.
_static_dir = Path(__file__).resolve().parent.parent / "static"
app.mount("/", StaticFiles(directory=_static_dir, html=True), name="static")
