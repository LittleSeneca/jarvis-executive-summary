"""Authentication and HTTP client setup for the OSINT plugin.

All OSINT sources are public or use free-tier API keys. Clients are pre-configured
with a 30-second timeout. Sources that require a key are set to None when the key
is absent; the plugin marks those sources as skipped.
"""

import os
from dataclasses import dataclass

import httpx

__all__ = ["OSINTClients", "get_authenticated_clients"]

_TIMEOUT = 30.0
_USER_AGENT = "Jarvis/1.0 (+https://github.com/LittleSeneca/jarvis-executive-summary; osint-plugin)"


@dataclass
class OSINTClients:
    """One pre-configured AsyncClient per OSINT source."""

    kev: httpx.AsyncClient
    nvd: httpx.AsyncClient
    urlhaus: httpx.AsyncClient | None  # None if OSINT_URLHAUS_API_KEY not set
    threatfox: httpx.AsyncClient | None  # None if OSINT_THREATFOX_API_KEY not set
    feodo: httpx.AsyncClient
    otx: httpx.AsyncClient | None  # None if OSINT_OTX_API_KEY not set


async def get_authenticated_clients() -> OSINTClients:
    """Build and return pre-configured AsyncClients for all OSINT sources.

    Sources with optional keys return None when the key is absent.
    """
    nvd_key = os.environ.get("OSINT_NVD_API_KEY", "").strip()
    urlhaus_key = os.environ.get("OSINT_URLHAUS_API_KEY", "").strip()
    threatfox_key = os.environ.get("OSINT_THREATFOX_API_KEY", "").strip()
    otx_key = os.environ.get("OSINT_OTX_API_KEY", "").strip()

    base_headers = {"User-Agent": _USER_AGENT}

    kev = httpx.AsyncClient(headers=base_headers, timeout=_TIMEOUT, follow_redirects=True)

    nvd_headers = dict(base_headers)
    if nvd_key:
        nvd_headers["apiKey"] = nvd_key
    nvd = httpx.AsyncClient(headers=nvd_headers, timeout=_TIMEOUT, follow_redirects=True)

    urlhaus: httpx.AsyncClient | None = None
    if urlhaus_key:
        urlhaus = httpx.AsyncClient(
            headers={**base_headers, "Auth-Key": urlhaus_key},
            timeout=_TIMEOUT,
            follow_redirects=True,
        )

    threatfox: httpx.AsyncClient | None = None
    if threatfox_key:
        threatfox = httpx.AsyncClient(
            headers={**base_headers, "Auth-Key": threatfox_key},
            timeout=_TIMEOUT,
            follow_redirects=True,
        )

    feodo = httpx.AsyncClient(headers=base_headers, timeout=_TIMEOUT, follow_redirects=True)

    otx: httpx.AsyncClient | None = None
    if otx_key:
        otx = httpx.AsyncClient(
            headers={**base_headers, "X-OTX-API-KEY": otx_key},
            timeout=_TIMEOUT,
            follow_redirects=True,
        )

    return OSINTClients(
        kev=kev,
        nvd=nvd,
        urlhaus=urlhaus,
        threatfox=threatfox,
        feodo=feodo,
        otx=otx,
    )
