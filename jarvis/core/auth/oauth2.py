"""OAuth2 refresh-token exchange helper."""

import httpx

__all__ = ["exchange_refresh_token"]


async def exchange_refresh_token(
    token_url: str,
    client_id: str,
    client_secret: str,
    refresh_token: str,
    extra_params: dict | None = None,
) -> str:
    """Exchange a refresh token for a fresh access token and return it."""
    data = {
        "grant_type": "refresh_token",
        "client_id": client_id,
        "client_secret": client_secret,
        "refresh_token": refresh_token,
    }
    if extra_params:
        data.update(extra_params)

    async with httpx.AsyncClient() as client:
        resp = await client.post(token_url, data=data)
        resp.raise_for_status()
        return resp.json()["access_token"]
