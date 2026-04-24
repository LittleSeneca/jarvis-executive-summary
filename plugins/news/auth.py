"""Authentication for the news plugin.

Public RSS feeds require no credentials. Return a bare AsyncClient with a
descriptive User-Agent so feed servers can identify the requester.
"""

import httpx

__all__ = ["get_authenticated_client"]

_USER_AGENT = "Jarvis/1.0 (+https://github.com/LittleSeneca/jarvis-executive-summary; news-plugin)"


def get_authenticated_client() -> httpx.AsyncClient:
    """Return an AsyncClient with a descriptive User-Agent."""
    return httpx.AsyncClient(
        headers={"User-Agent": _USER_AGENT},
        follow_redirects=True,
        timeout=10.0,
    )
