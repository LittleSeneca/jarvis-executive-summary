"""Site24x7 data-source plugin — open alerts, server performance, and disk utilization."""

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

# Site24x7 status codes: 1=UP, 0=DOWN, 2=TROUBLE, 5=MAINTENANCE, 7=UNKNOWN
_DOWN_STATUSES = {0, 2, 7}
_STATUS_LABELS = {0: "DOWN", 1: "UP", 2: "TROUBLE", 5: "MAINTENANCE", 7: "UNKNOWN"}

_DISK_ALERT_THRESHOLD = 80.0


class Site24x7Plugin(DataSourcePlugin):
    """Fetch open alerts, server CPU/memory averages, and disk utilization from Site24x7."""

    name = "site24x7"
    display_name = "Site24x7"
    required_env_vars = [
        "SITE24X7_ZOHO_REFRESH_TOKEN",
        "SITE24X7_CLIENT_ID",
        "SITE24X7_CLIENT_SECRET",
    ]
    temperature = 0.2
    max_tokens = 600

    async def fetch(self, window_hours: int) -> FetchResult:
        """Pull open alerts and server performance from Site24x7."""
        try:
            client = await get_authenticated_client()
        except PluginAuthError:
            raise

        try:
            async with client:
                open_alerts, server_perf = await asyncio.gather(
                    _get_open_alerts(client),
                    _get_server_performance(client),
                )
        except PluginAuthError:
            raise
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code == 401:
                raise PluginAuthError("Site24x7 API rejected credentials (401)") from exc
            raise PluginFetchError(
                "Site24x7 API HTTP error %s" % exc.response.status_code
            ) from exc
        except httpx.RequestError as exc:
            raise PluginFetchError("Network error reaching Site24x7: %s" % exc) from exc
        except Exception as exc:
            log.exception("Unexpected error in Site24x7 fetch")
            raise PluginFetchError("Unexpected error in Site24x7 fetch: %s" % exc) from exc

        high_disk = [s for s in server_perf if s.get("max_disk_pct") is not None
                     and s["max_disk_pct"] > _DISK_ALERT_THRESHOLD]

        payload = {
            "window_hours": window_hours,
            "open_alerts": open_alerts,
            "server_performance": server_perf,
            "high_disk_servers": high_disk,
        }

        log.info(
            "Site24x7 fetch: %d open alerts, %d servers reporting, %d high-disk",
            len(open_alerts),
            len(server_perf),
            len(high_disk),
        )
        return FetchResult(
            source_name=self.display_name,
            raw_payload=payload,
            metadata={
                "window_hours": window_hours,
                "open_alerts_count": len(open_alerts),
                "servers_reporting": len(server_perf),
                "high_disk_count": len(high_disk),
                "fetched_at": datetime.now(UTC).isoformat(),
            },
        )

    def redact(self, payload: Any) -> Any:
        return payload

    def format_table(self, payload: Any) -> str | None:
        from tabulate import tabulate

        servers = payload.get("server_performance", [])
        if not servers:
            return None

        def fmt(v: float | None) -> str:
            return f"{v}%" if v is not None else "—"

        rows = [
            [s["name"], fmt(s.get("avg_cpu_pct")), fmt(s.get("avg_mem_pct")), fmt(s.get("max_disk_pct"))]
            for s in servers
        ]
        table = tabulate(rows, headers=["Server", "CPU", "RAM", "Disk"], tablefmt="outline")
        return f"```\n{table}\n```"


async def _get_open_alerts(client: httpx.AsyncClient) -> list[dict]:
    """Return monitors currently in a non-UP state."""
    resp = await client.get("/current_status")
    if resp.status_code == 401:
        raise PluginAuthError("Site24x7 rejected credentials fetching current status")
    resp.raise_for_status()
    monitors = resp.json().get("data", {}).get("monitors", [])
    alerts = []
    for m in monitors:
        status_code = m.get("status")
        if status_code in _DOWN_STATUSES:
            alerts.append({
                "name": m.get("name", ""),
                "type": m.get("monitor_type", ""),
                "status": _STATUS_LABELS.get(status_code, str(status_code)),
                "last_polled": m.get("last_polled_time", ""),
            })
    return alerts


async def _get_server_performance(client: httpx.AsyncClient) -> list[dict]:
    """Return 24h avg CPU/memory and max disk per server that has agent data."""
    resp = await client.get("/reports/performance", params={"period": "1"}, timeout=60.0)
    if resp.status_code == 401:
        raise PluginAuthError("Site24x7 rejected credentials fetching performance")
    resp.raise_for_status()

    server_group = resp.json().get("data", {}).get("group_data", {}).get("SERVER", {})
    names: list[str] = server_group.get("name", [])
    attr_data: list[dict] = server_group.get("attribute_data", [])

    # attribute_data is a list indexed by server position — attr_data[i] holds metrics
    # for names[i]. The inner key (always "0") is a slot placeholder, not a server index.
    result = []
    for server_idx, entry in enumerate(attr_data):
        if server_idx >= len(names):
            break
        metrics = next(iter(entry.values()), {}) if entry else {}

        def _val(key: str) -> float | None:
            v = metrics.get(key)
            if v is None or v == "-":
                return None
            try:
                return float(v)
            except (TypeError, ValueError):
                return None

        cpu = _val("CPUUSEDPERCENT")
        mem = _val("MEMUSEDPERCENT")
        disk = _val("DISKUSEDPERCENT")

        if cpu is None and mem is None:
            continue  # no agent data for this server

        result.append({
            "name": names[server_idx],
            "avg_cpu_pct": round(cpu, 1) if cpu is not None else None,
            "avg_mem_pct": round(mem, 1) if mem is not None else None,
            "max_disk_pct": round(disk, 1) if disk is not None else None,
        })

    return result
