"""Authentication for the Trump / Truth Social plugin."""

import httpx

__all__ = ["get_authenticated_client"]

_USER_AGENT = (
    "Jarvis-Executive-Summary/1.0 "
    "(https://github.com/LittleSeneca/jarvis-executive-summary; "
    "open-source morning-brief agent)"
)


def get_authenticated_client() -> httpx.AsyncClient:
    """Return an AsyncClient with a descriptive User-Agent. No credentials required."""
    return httpx.AsyncClient(
        headers={"User-Agent": _USER_AGENT},
        follow_redirects=True,
    )
