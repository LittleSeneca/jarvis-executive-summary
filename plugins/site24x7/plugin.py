"""Site24x7 data-source plugin — alerts, monitor status, and SLA summary."""

import asyncio
import logging
from datetime import UTC, datetime
from typing import Any

import httpx

from jarvis.core.exceptions import PluginAuthError, PluginFetchError
from jarvis.core.plugin import DataSourcePlugin, FetchResult

from .auth import get_authenticated_client

__all__ = ["Site24x7Plugin"]

log = logging.getLogger(__name__)


class Site24x7Plugin(DataSourcePlugin):
    """Fetch alert logs, current monitor status, and SLA summary from Site24x7."""

    name = "site24x7"
    display_name = "Site24x7"
    required_env_vars = [
        "SITE24X7_ZOHO_REFRESH_TOKEN",
        "SITE24X7_CLIENT_ID",
        "SITE24X7_CLIENT_SECRET",
    ]
    temperature = 0.2
    max_tokens = 700

    async def fetch(self, window_hours: int) -> FetchResult:
        """Pull alert logs, down monitors, and SLA summary from Site24x7."""
        try:
            client = await get_authenticated_client()
        except PluginAuthError:
            raise

        try:
            async with client:
                alerts, down_monitors, sla_at_risk = await _fetch_all(client)
        except PluginAuthError:
            raise
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code == 401:
                raise PluginAuthError(
                    "Site24x7 API rejected credentials (401)"
                ) from exc
            raise PluginFetchError(
                "Site24x7 API HTTP error %s" % exc.response.status_code
            ) from exc
        except httpx.RequestError as exc:
            raise PluginFetchError("Network error reaching Site24x7 API: %s" % exc) from exc
        except Exception as exc:
            log.exception("Unexpected error in Site24x7 fetch")
            raise PluginFetchError("Unexpected error in Site24x7 fetch: %s" % exc) from exc

        payload = {
            "window_hours": window_hours,
            "alerts": alerts,
            "down_monitors": down_monitors,
            "sla_at_risk": sla_at_risk,
        }

        log.info(
            "Site24x7 fetch complete: %d alerts, %d down monitors, %d SLA at risk",
            len(alerts),
            len(down_monitors),
            len(sla_at_risk),
        )
        return FetchResult(
            source_name=self.display_name,
            raw_payload=payload,
            metadata={
                "window_hours": window_hours,
                "alerts_count": len(alerts),
                "down_monitors_count": len(down_monitors),
                "sla_at_risk_count": len(sla_at_risk),
                "fetched_at": datetime.now(UTC).isoformat(),
            },
        )

    def redact(self, payload: Any) -> Any:
        """No sensitive data to redact in Site24x7 payloads."""
        return payload


async def _fetch_all(
    client: httpx.AsyncClient,
) -> tuple[list[dict], list[dict], list[dict]]:
    """Run the three Site24x7 API calls concurrently."""
    alerts_coro = _get_alert_logs(client)
    status_coro = _get_current_status(client)
    sla_coro = _get_sla_summary(client)

    alerts, down_monitors, sla_at_risk = await asyncio.gather(
        alerts_coro, status_coro, sla_coro
    )
    return alerts, down_monitors, sla_at_risk


async def _get_alert_logs(client: httpx.AsyncClient) -> list[dict]:
    """Fetch recent alert log summary."""
    resp = await client.get("/alert_logs/summary", params={"period": "1d"})
    if resp.status_code == 401:
        raise PluginAuthError("Site24x7 rejected credentials (401) fetching alert logs")
    resp.raise_for_status()
    data = resp.json()
    items = _extract_list(data)
    return [
        {
            "monitor": item.get("display_name", item.get("monitor_name", "")),
            "type": item.get("alert_type", item.get("type", "")),
            "status": item.get("status", ""),
            "occurred": item.get("occurred_time", item.get("start_time", "")),
        }
        for item in items
    ]


async def _get_current_status(client: httpx.AsyncClient) -> list[dict]:
    """Fetch monitors currently in DOWN or TROUBLE state."""
    resp = await client.get("/current_status")
    if resp.status_code == 401:
        raise PluginAuthError("Site24x7 rejected credentials (401) fetching current status")
    resp.raise_for_status()
    data = resp.json()
    items = _extract_list(data)
    down_states = {"DOWN", "TROUBLE", "0", "2"}
    return [
        {
            "name": item.get("display_name", item.get("name", "")),
            "type": item.get("monitor_type", item.get("type", "")),
            "status": item.get("status", ""),
            "last_checked": item.get("last_polled_time", item.get("last_checked_at", "")),
            "unit": item.get("unit", ""),
        }
        for item in items
        if str(item.get("status", "")).upper() in down_states
        or item.get("status") in (0, 2)
    ]


async def _get_sla_summary(client: httpx.AsyncClient) -> list[dict]:
    """Fetch SLA summary — return only breached or at-risk entries."""
    resp = await client.get("/sla/summary")
    if resp.status_code == 401:
        raise PluginAuthError("Site24x7 rejected credentials (401) fetching SLA summary")
    resp.raise_for_status()
    data = resp.json()
    items = _extract_list(data)
    result = []
    for item in items:
        breach_status = str(item.get("breach_status", "")).upper()
        # Include breached or at-risk (or any non-empty breach_status the API returns)
        if breach_status in ("BREACHED", "AT_RISK", "TRUE", "1") or item.get("breached"):
            availability = item.get("availability", item.get("current_availability"))
            target = item.get("target_availability", item.get("availability_threshold"))
            result.append(
                {
                    "monitor": item.get("display_name", item.get("monitor_name", "")),
                    "sla": item.get("sla_name", item.get("name", "")),
                    "availability_pct": _to_float(availability),
                    "target_pct": _to_float(target),
                    "breached": breach_status in ("BREACHED", "TRUE", "1") or bool(item.get("breached")),
                }
            )
    return result


def _extract_list(data: Any) -> list[dict]:
    """Unpack Site24x7 response envelope — handles list or {'data': [...]} shapes."""
    if isinstance(data, list):
        return data
    if isinstance(data, dict):
        return data.get("data", [])
    return []


def _to_float(value: Any) -> float | None:
    """Convert availability value to float, returning None if not parseable."""
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None
