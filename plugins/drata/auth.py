"""Authentication for the Drata plugin."""

import os

import httpx

from jarvis.core.auth.api_key import bearer_client
from jarvis.core.exceptions import PluginAuthError

__all__ = ["get_authenticated_client"]

_DEFAULT_BASE_URL = "https://public-api.drata.com"


def get_authenticated_client() -> httpx.AsyncClient:
    """Return an AsyncClient with Authorization: Bearer <DRATA_API_KEY>."""
    api_key = os.environ.get("DRATA_API_KEY", "").strip()
    if not api_key:
        raise PluginAuthError("DRATA_API_KEY is not set")
    base_url = os.environ.get("DRATA_BASE_URL", _DEFAULT_BASE_URL).strip() or _DEFAULT_BASE_URL
    return bearer_client(api_key, base_url=base_url)
