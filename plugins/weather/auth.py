"""Authentication for the Weather plugin."""

import os

import httpx

from jarvis.core.exceptions import PluginAuthError

__all__ = ["get_authenticated_client"]

_BASE_URL = "https://api.openweathermap.org"


def get_authenticated_client() -> httpx.AsyncClient:
    """Return an AsyncClient with the OpenWeatherMap API key as a default query param."""
    api_key = os.environ.get("WEATHER_API_KEY", "").strip()
    if not api_key:
        raise PluginAuthError("WEATHER_API_KEY is not set")
    return httpx.AsyncClient(
        base_url=_BASE_URL,
        params={"appid": api_key},
    )
