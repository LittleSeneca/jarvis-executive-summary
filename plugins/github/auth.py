"""Authentication for the GitHub plugin."""

import os

import httpx

from jarvis.core.exceptions import PluginAuthError

__all__ = ["get_authenticated_client"]

_BASE_URL = "https://api.github.com"


def get_authenticated_client() -> httpx.AsyncClient:
    """Return an AsyncClient with GitHub PAT bearer auth."""
    token = os.environ.get("GITHUB_TOKEN", "").strip()
    if not token:
        raise PluginAuthError("GITHUB_TOKEN is not set")
    return httpx.AsyncClient(
        base_url=_BASE_URL,
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        },
    )
