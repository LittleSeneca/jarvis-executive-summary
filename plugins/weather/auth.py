"""Authentication for the Weather plugin — Open-Meteo requires no API key."""

import httpx

__all__ = ["get_authenticated_client"]

_USER_AGENT = "Jarvis-Executive-Summary/0.1 (personal digest; github.com/LittleSeneca/jarvis-executive-summary)"


def get_authenticated_client() -> httpx.AsyncClient:
    """Return a plain AsyncClient — Open-Meteo and Nominatim require no credentials."""
    return httpx.AsyncClient(
        headers={"User-Agent": _USER_AGENT},
        timeout=15.0,
    )
