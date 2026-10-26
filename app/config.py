"""Application settings from the environment / .env (documented in .env.example).

Secrets (PROTON_ICS_URL) come only from the environment / git-ignored .env.
"""

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # --- Local bind (loopback only; the kiosk browser is the sole client) ---
    host: str = "127.0.0.1"
    port: int = 8000

    # --- Weather (Open-Meteo) ---
    # Deliberately non-personal example default (NYC); set the real one in .env.
    weather_lat: float = 40.7128
    weather_lon: float = -74.0060
    weather_ttl_seconds: int = 900

    # --- Weather: model + optional NWS observation overlay ---
    # Open-Meteo `models=` param. US deployments may prefer "ncep_nbm_conus"
    # (NOAA's calibrated blend); judge over ~2 weeks before pinning.
    weather_model: str = "best_match"
    # NWS station ID (e.g. "KOQT") for observed current conditions on the hero.
    # US-only; empty = disabled.
    nws_station: str = ""
    # api.weather.gov requires a User-Agent and asks for contact info.
    nws_user_agent: str = "pi-dashboard (https://github.com/edwcmiller3/pi-dashboard)"

    # --- Calendar (Proton ICS) ---
    # PROTON_ICS_URL is secret + PII-bearing - set it in .env, never commit it.
    proton_ics_url: str = ""
    calendar_ttl_seconds: int = 900

    # --- Cache ---
    cache_dir: str = "var"

    # --- Theme (optional palette override) ---
    # Stylesheet name in static/themes/ (no ".css"), served at /theme.css.
    # Empty = built-in palette.
    theme: str = ""

    # --- Layout (which UI design renders) ---
    # Directory under static/layouts/, served at /layout.js and /layout.css. An
    # invalid name falls back to classic (the kiosk must never blank).
    layout: str = "classic"

    # --- Icon pack (which weather-icon set renders) ---
    # An invalid name falls back to weather-icons (the kiosk must never blank).
    icon_pack: str = "weather-icons"


settings = Settings()
