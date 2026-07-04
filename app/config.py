"""Application settings, loaded from the environment / .env via pydantic-settings.

Every field here is documented in .env.example. Secrets (PROTON_ICS_URL) must come
from the environment / .env (git-ignored) — never hard-coded. See README "Secrets".
"""

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # --- Local bind (spec §5) ---
    host: str = "127.0.0.1"
    port: int = 8000

    # --- Weather (Open-Meteo) ---
    # Example default (NYC City Hall). Set WEATHER_LAT/WEATHER_LON in .env to your
    # actual location — these are env-overridable and intentionally not personal.
    weather_lat: float = 40.7128
    weather_lon: float = -74.0060
    weather_ttl_seconds: int = 900

    # --- Calendar (Proton ICS) ---
    # PROTON_ICS_URL is secret + PII-bearing — set it in .env, never commit it.
    proton_ics_url: str = ""
    calendar_ttl_seconds: int = 900

    # --- Cache (JSON now; SQLite-swappable later) ---
    cache_dir: str = "var"

    # --- Theme (optional palette override) ---
    # Name of a stylesheet in static/themes/ (without ".css") served at
    # /theme.css to override the :root palette vars. Empty = built-in palette.
    theme: str = ""


settings = Settings()
