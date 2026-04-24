"""Drata compliance data-source plugin."""

import asyncio
import logging
from collections import Counter
from datetime import UTC, datetime
from typing import Any

import httpx

from jarvis.core.exceptions import PluginAuthError, PluginFetchError
from jarvis.core.plugin import DataSourcePlugin, FetchResult

from .auth import get_authenticated_client

__all__ = ["DrataPlugin"]

log = logging.getLogger(__name__)

_PAGE_SIZE = 50
_MONITOR_PAGE_CAP = 6    # up to 300 monitors
_PERSONNEL_PAGE_CAP = 10  # up to 500 personnel


class DrataPlugin(DataSourcePlugin):
    """Fetch monitor health and personnel compliance status from Drata."""

    name = "drata"
    display_name = "Drata"
    required_env_vars = ["DRATA_API_KEY"]
    temperature = 0.2
    max_tokens = 800

    async def fetch(self, window_hours: int) -> FetchResult:
        """Pull compliance posture from Drata."""
        try:
            client = get_authenticated_client()
        except PluginAuthError:
            raise

        try:
            async with client:
                monitors_raw, personnel_raw = await asyncio.gather(
                    _paginate_parallel(client, "/public/monitors", _MONITOR_PAGE_CAP),
                    _paginate_parallel(client, "/public/personnel", _PERSONNEL_PAGE_CAP),
                )
        except PluginAuthError:
            raise
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code in (401, 403):
                raise PluginAuthError(
                    "Drata API rejected credentials (HTTP %s)" % exc.response.status_code
                ) from exc
            raise PluginFetchError(
                "Drata API HTTP error %s" % exc.response.status_code
            ) from exc
        except httpx.RequestError as exc:
            raise PluginFetchError("Network error reaching Drata: %s" % exc) from exc
        except Exception as exc:
            log.exception("Unexpected error in Drata fetch")
            raise PluginFetchError("Unexpected error in Drata fetch: %s" % exc) from exc

        monitors = _process_monitors(monitors_raw)
        personnel = _process_personnel(personnel_raw)

        payload = {
            "window_hours": window_hours,
            "monitors": monitors,
            "personnel": personnel,
        }

        log.info(
            "Drata fetch: %d monitors (%d failed), %d unhealthy personnel",
            monitors["total"],
            len(monitors["all_failed"]),
            len(personnel["unhealthy"]),
        )
        return FetchResult(
            source_name=self.display_name,
            raw_payload=payload,
            metadata={
                "window_hours": window_hours,
                "monitors_total": monitors["total"],
                "monitors_failed": len(monitors["all_failed"]),
                "personnel_unhealthy": len(personnel["unhealthy"]),
                "fetched_at": datetime.now(UTC).isoformat(),
            },
        )

    def redact(self, payload: Any) -> Any:
        return payload

    def format_table(self, payload: Any) -> str | None:
        from tabulate import tabulate

        failed = payload.get("monitors", {}).get("all_failed", [])
        if not failed:
            return None
        rows = [[m["name"], m.get("priority", "—"), m.get("last_check", "—")] for m in failed]
        table = tabulate(rows, headers=["Monitor", "Priority", "Last Check"], tablefmt="outline")
        return f"```\n{table}\n```"


async def _fetch_page(client: httpx.AsyncClient, path: str, offset: int, **params: Any) -> list[dict]:
    resp = await client.get(path, params={"offset": offset, "limit": _PAGE_SIZE, **params})
    resp.raise_for_status()
    return resp.json().get("data", [])


async def _paginate_parallel(
    client: httpx.AsyncClient, path: str, max_pages: int, **params: Any
) -> list[dict]:
    """Fetch page 0 first, then fire remaining pages concurrently up to max_pages."""
    first = await _fetch_page(client, path, 0, **params)
    if len(first) < _PAGE_SIZE:
        return first
    offsets = [i * _PAGE_SIZE for i in range(1, max_pages)]
    rest_pages = await asyncio.gather(
        *[_fetch_page(client, path, off, **params) for off in offsets]
    )
    items = list(first)
    for page in rest_pages:
        items.extend(page)
        if len(page) < _PAGE_SIZE:
            break
    return items


def _process_monitors(raw: list[dict]) -> dict:
    seen_ids: set[int] = set()
    result = []
    for m in raw:
        mid = m.get("id")
        if mid in seen_ids:
            continue
        seen_ids.add(mid)
        inst = (m.get("monitorInstances") or [{}])[0]
        result.append({
            "id": mid,
            "name": m.get("name", ""),
            "status": m.get("checkResultStatus", "UNKNOWN"),
            "priority": m.get("priority", ""),
            "last_check": (m.get("lastCheck") or "")[:10],
            "failed_description": inst.get("failedTestDescription", ""),
            "remedy": inst.get("remedyDescription", ""),
        })

    by_status = dict(Counter(m["status"] for m in result))
    all_failed = [m for m in result if m["status"] == "FAILED"]

    return {
        "total": len(result),
        "by_status": by_status,
        "all_failed": all_failed,
    }


def _extract_name(person: dict) -> str:
    """Return display name from Google identity, falling back to email."""
    user = person.get("user") or {}
    identities = user.get("identities") or []
    for identity in identities:
        conn = identity.get("connection") or {}
        if conn.get("clientType") == "GOOGLE":
            first = (identity.get("firstName") or "").strip()
            last = (identity.get("lastName") or "").strip()
            name = f"{first} {last}".strip()
            if name:
                return name
    return user.get("email", "Unknown")


def _process_personnel(raw: list[dict]) -> dict:
    seen_ids: set[int] = set()
    unhealthy = []

    for person in raw:
        pid = person.get("id")
        if pid in seen_ids:
            continue
        seen_ids.add(pid)

        if person.get("employmentStatus") not in ("CURRENT_EMPLOYEE", "CURRENT_CONTRACTOR"):
            continue

        checks = person.get("complianceChecks") or []
        full = next((c for c in checks if c.get("type") == "FULL_COMPLIANCE"), None)
        if not full or full.get("status") != "FAIL":
            continue

        failing = [
            c.get("type", "UNKNOWN")
            for c in checks
            if c.get("status") == "FAIL" and c.get("type") != "FULL_COMPLIANCE"
        ]

        unhealthy.append({
            "name": _extract_name(person),
            "employment_status": person.get("employmentStatus"),
            "failing_checks": failing,
        })

    check_counts: Counter = Counter()
    for p in unhealthy:
        for check in p["failing_checks"]:
            check_counts[check] += 1

    return {
        "unhealthy": unhealthy,
        "check_summary": dict(check_counts.most_common(10)),
    }
