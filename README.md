# pi-dashboard

A weather & calendar dashboard for a wall-mounted Raspberry Pi 5 touchscreen
(Pi OS Lite + labwc + Chromium kiosk). FastAPI backend serves a static dashboard
that the on-Pi Chromium kiosk points at over `http://localhost`.

See the build plan and spec (Obsidian vault) for the full design.

## Requirements

- Python 3.13.5 (pinned via `.python-version`; provisioned by `uv`)
- [`uv`](https://docs.astral.sh/uv/) for dependency / venv management

## Setup

```sh
uv sync                 # create the venv, install deps from uv.lock
cp .env.example .env     # then fill in PROTON_ICS_URL (see Secrets below)
```

## Run

```sh
uv run uvicorn app.main:app --reload    # dev (Mac): http://127.0.0.1:8000
```

`/healthz` returns `{"status": "ok"}`. The static dashboard is served at `/`,
and `/api/data` serves the normalized weather/calendar contract the dashboard
polls (a background loop refreshes it; weather is live, calendar lands in Phase 5).
The JS unit tests run with `node --test` from `static/`.

## Test / lint

```sh
uv run pytest
uv run ruff check .
uv run ruff format .
uv run mypy             # strict type-check gate (app + tests)
```

## Secrets & data handling

`PROTON_ICS_URL` is the Proton Calendar "Full view" ICS link. **The URL embeds the
decryption key inline**, so it is a credential *and* exposes calendar PII (event
titles, descriptions, participants, locations). Keep it in 1Password; put it only
in the git-ignored `.env`; never commit it, paste it into logs/shell history, or
share it. This is a personal project on a personal GitHub account by design — the
calendar PII stays out of any org tooling.

## Attribution

Weather data by [Open-Meteo.com](https://open-meteo.com/), licensed under
[CC BY 4.0](https://creativecommons.org/licenses/by/4.0/).
