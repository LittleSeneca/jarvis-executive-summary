"""Authentication for the Site24x7 plugin."""

import os

import httpx

from jarvis.core.auth.oauth2 import exchange_refresh_token
from jarvis.core.exceptions import PluginAuthError

__all__ = ["get_authenticated_client", "datacenter_urls"]

_SCOPE = "Site24x7.Reports.Read,Site24x7.Operations.Read"

_DC_MAP: dict[str, tuple[str, str]] = {
    "us": ("https://accounts.zoho.com/oauth/v2/token", "https://www.site24x7.com/api"),
    "eu": ("https://accounts.zoho.eu/oauth/v2/token", "https://www.site24x7.eu/api"),
    "in": ("https://accounts.zoho.in/oauth/v2/token", "https://www.site24x7.in/api"),
    "au": ("https://accounts.zoho.com.au/oauth/v2/token", "https://www.site24x7.com.au/api"),
    "cn": ("https://accounts.zoho.com.cn/oauth/v2/token", "https://www.site24x7.cn/api"),
    "jp": ("https://accounts.zoho.jp/oauth/v2/token", "https://www.site24x7.jp/api"),
}


def datacenter_urls(dc: str) -> tuple[str, str]:
    """Return (token_url, api_base_url) for the given datacenter code."""
    key = dc.lower().strip()
    if key not in _DC_MAP:
        raise PluginAuthError(
            "Unknown SITE24X7_DATACENTER '%s'. Valid values: %s" % (dc, ", ".join(_DC_MAP))
        )
    return _DC_MAP[key]


async def get_authenticated_client() -> httpx.AsyncClient:
    """Exchange the Zoho refresh token and return an authenticated AsyncClient."""
    refresh_token = os.environ.get("SITE24X7_ZOHO_REFRESH_TOKEN", "").strip()
    client_id = os.environ.get("SITE24X7_CLIENT_ID", "").strip()
    client_secret = os.environ.get("SITE24X7_CLIENT_SECRET", "").strip()

    missing = [
        var
        for var, val in (
            ("SITE24X7_ZOHO_REFRESH_TOKEN", refresh_token),
            ("SITE24X7_CLIENT_ID", client_id),
            ("SITE24X7_CLIENT_SECRET", client_secret),
        )
        if not val
    ]
    if missing:
        raise PluginAuthError("Site24x7: missing required env vars: %s" % ", ".join(missing))

    dc = os.environ.get("SITE24X7_DATACENTER", "us").strip() or "us"
    token_url, api_base_url = datacenter_urls(dc)

    try:
        access_token = await exchange_refresh_token(
            token_url,
            client_id,
            client_secret,
            refresh_token,
            extra_params={"scope": _SCOPE},
        )
    except Exception as exc:
        raise PluginAuthError("Site24x7 token exchange failed: %s" % exc) from exc

    return httpx.AsyncClient(
        base_url=api_base_url,
        headers={"Authorization": "Zoho-oauthtoken %s" % access_token},
    )
