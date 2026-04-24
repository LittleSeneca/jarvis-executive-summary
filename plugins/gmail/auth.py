"""Authentication for the Gmail plugin."""

import os

import httpx

from jarvis.core.auth.oauth2 import exchange_refresh_token
from jarvis.core.exceptions import PluginAuthError

__all__ = ["get_authenticated_client"]

_TOKEN_URL = "https://oauth2.googleapis.com/token"
_BASE_URL = "https://gmail.googleapis.com"
_SCOPE = "https://www.googleapis.com/auth/gmail.readonly"


async def get_authenticated_client() -> httpx.AsyncClient:
    """Exchange the Gmail refresh token and return an authenticated AsyncClient."""
    client_id = os.environ.get("GMAIL_CLIENT_ID", "").strip()
    client_secret = os.environ.get("GMAIL_CLIENT_SECRET", "").strip()
    refresh_token = os.environ.get("GMAIL_REFRESH_TOKEN", "").strip()

    missing = [
        var
        for var, val in (
            ("GMAIL_CLIENT_ID", client_id),
            ("GMAIL_CLIENT_SECRET", client_secret),
            ("GMAIL_REFRESH_TOKEN", refresh_token),
        )
        if not val
    ]
    if missing:
        raise PluginAuthError("Gmail: missing required env vars: %s" % ", ".join(missing))

    try:
        access_token = await exchange_refresh_token(
            _TOKEN_URL,
            client_id,
            client_secret,
            refresh_token,
            extra_params={"scope": _SCOPE},
        )
    except Exception as exc:
        raise PluginAuthError("Gmail token exchange failed: %s" % exc) from exc

    return httpx.AsyncClient(
        base_url=_BASE_URL,
        headers={"Authorization": "Bearer %s" % access_token},
    )
