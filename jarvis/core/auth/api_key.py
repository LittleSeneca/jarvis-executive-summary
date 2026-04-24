"""Helper for API-key authenticated HTTP clients."""

import httpx

__all__ = ["bearer_client", "api_key_client"]


def bearer_client(token: str, **kwargs) -> httpx.AsyncClient:
    """Return an AsyncClient with Authorization: Bearer <token>."""
    headers = kwargs.pop("headers", {})
    headers["Authorization"] = f"Bearer {token}"
    return httpx.AsyncClient(headers=headers, **kwargs)


def api_key_client(key: str, header: str = "X-API-Key", **kwargs) -> httpx.AsyncClient:
    """Return an AsyncClient with a custom API-key header."""
    headers = kwargs.pop("headers", {})
    headers[header] = key
    return httpx.AsyncClient(headers=headers, **kwargs)
