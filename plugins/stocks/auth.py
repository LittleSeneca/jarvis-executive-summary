"""Authentication for the stocks plugin.

yfinance (default provider) needs no credentials. Alpha Vantage requires
an API key — that path is stubbed and will raise PluginFetchError if used.
"""

import os

import httpx

__all__ = ["get_authenticated_client"]

_USER_AGENT = "Jarvis/1.0 (+https://github.com/LittleSeneca/jarvis-executive-summary; stocks-plugin)"


def get_authenticated_client() -> httpx.AsyncClient | None:
    """Return an authenticated client, or None for yfinance (no HTTP client needed)."""
    provider = os.environ.get("STOCKS_PROVIDER", "yfinance").lower()
    if provider == "yfinance":
        return None
    if provider == "alpha_vantage":
        api_key = os.environ.get("ALPHA_VANTAGE_API_KEY", "")
        if not api_key:
            return None  # let plugin.py surface the error with PluginFetchError
        return httpx.AsyncClient(
            headers={
                "User-Agent": _USER_AGENT,
            },
            timeout=15.0,
            params={"apikey": api_key},
        )
    return None
