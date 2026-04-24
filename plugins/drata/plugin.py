"""Drata compliance data-source plugin."""

import asyncio
import logging
import os
import re
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx

from jarvis.core.exceptions import PluginAuthError, PluginFetchError
from jarvis.core.plugin import DataSourcePlugin, FetchResult

from .auth import get_authenticated_client

__all__ = ["DrataPlugin"]

log = logging.getLogger(__name__)

_EMAIL_RE = re.compile(r"[^@\s]+@[^@\s]+\.[^@\s]+")


class DrataPlugin(DataSourcePlugin):
    """Fetch failing controls, overdue tasks, and evidence requests from Drata."""

    name = "drata"
    display_name = "Drata"
    required_env_vars = ["DRATA_API_KEY"]
    temperature = 0.2
    max_tokens = 600

    async def fetch(self, window_hours: int) -> FetchResult:
        """Pull compliance posture from Drata for the last window_hours."""
        window_start = datetime.now(UTC) - timedelta(hours=window_hours)

        try:
            client = get_authenticated_client()
        except PluginAuthError:
            raise

        try:
            async with client:
                failing_controls, overdue_tasks, due_soon_tasks, evidence_requests = (
                    await _fetch_all(client, window_start)
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

        payload = {
            "window_hours": window_hours,
            "failing_controls": failing_controls,
            "overdue_tasks": overdue_tasks,
            "due_soon_tasks": due_soon_tasks,
            "evidence_requests": evidence_requests,
        }

        log.info(
            "Drata fetch complete: %d failing controls, %d overdue tasks, "
            "%d due-soon tasks, %d evidence requests",
            len(failing_controls),
            len(overdue_tasks),
            len(due_soon_tasks),
            len(evidence_requests),
        )
        return FetchResult(
            source_name=self.display_name,
            raw_payload=payload,
            metadata={
                "window_hours": window_hours,
                "window_start": window_start.isoformat(),
                "failing_controls_count": len(failing_controls),
                "overdue_tasks_count": len(overdue_tasks),
                "due_soon_tasks_count": len(due_soon_tasks),
                "evidence_requests_count": len(evidence_requests),
                "fetched_at": datetime.now(UTC).isoformat(),
            },
        )

    def redact(self, payload: Any) -> Any:
        """Strip email addresses from personnel task assignee fields."""
        import copy

        redacted = copy.deepcopy(payload)
        for key in ("overdue_tasks", "due_soon_tasks"):
            for task in redacted.get(key, []):
                assignee = task.get("assignee")
                if assignee and _EMAIL_RE.match(str(assignee)):
                    task["assignee"] = assignee.split("@")[0]
        return redacted


async def _fetch_all(
    client: httpx.AsyncClient, window_start: datetime
) -> tuple[list[dict], list[dict], list[dict], list[dict]]:
    """Run all three Drata endpoint fetches concurrently."""
    failing_coro = _get_failing_controls(client)
    overdue_coro = _get_personnel_tasks(client, "OVERDUE")
    due_soon_coro = _get_personnel_tasks(client, "DUE_SOON")
    evidence_coro = _get_evidence_requests(client, window_start)

    failing_controls, overdue_tasks, due_soon_tasks, evidence_requests = await asyncio.gather(
        failing_coro, overdue_coro, due_soon_coro, evidence_coro
    )
    return failing_controls, overdue_tasks, due_soon_tasks, evidence_requests


async def _get_failing_controls(client: httpx.AsyncClient) -> list[dict]:
    """Fetch controls with FAILING status."""
    resp = await client.get("/v1/controls", params={"status": "FAILING"})
    resp.raise_for_status()
    data = resp.json()
    items = data if isinstance(data, list) else data.get("data", [])
    return [
        {
            "id": str(item.get("id", "")),
            "name": item.get("name", ""),
            "status": item.get("status", ""),
            "frameworks": [
                f.get("name", "") if isinstance(f, dict) else str(f)
                for f in item.get("frameworks", [])
            ],
        }
        for item in items
    ]


async def _get_personnel_tasks(client: httpx.AsyncClient, status: str) -> list[dict]:
    """Fetch personnel tasks filtered by status (OVERDUE or DUE_SOON)."""
    resp = await client.get("/v1/personnel/tasks", params={"status": status})
    resp.raise_for_status()
    data = resp.json()
    items = data if isinstance(data, list) else data.get("data", [])
    return [
        {
            "id": str(item.get("id", "")),
            "title": item.get("title", ""),
            "assignee": _extract_assignee_name(item.get("assignee")),
            "due_date": item.get("dueDate", item.get("due_date", "")),
            "status": item.get("status", status),
        }
        for item in items
    ]


async def _get_evidence_requests(
    client: httpx.AsyncClient, window_start: datetime
) -> list[dict]:
    """Fetch evidence requests created after window_start."""
    created_after = window_start.strftime("%Y-%m-%dT%H:%M:%SZ")
    resp = await client.get(
        "/v1/evidence-requests", params={"created_after": created_after}
    )
    resp.raise_for_status()
    data = resp.json()
    items = data if isinstance(data, list) else data.get("data", [])
    return [
        {
            "id": str(item.get("id", "")),
            "title": item.get("title", ""),
            "due_date": item.get("dueDate", item.get("due_date", "")),
            "status": item.get("status", ""),
        }
        for item in items
    ]


def _extract_assignee_name(assignee: Any) -> str:
    """Return just the first name (or identifier) from an assignee field."""
    if not assignee:
        return ""
    if isinstance(assignee, dict):
        name = assignee.get("name", "") or assignee.get("displayName", "")
        if not name:
            # Fall back to email-derived first name
            email = assignee.get("email", "")
            if email and _EMAIL_RE.match(email):
                return email.split("@")[0]
        return name
    value = str(assignee)
    if _EMAIL_RE.match(value):
        return value.split("@")[0]
    return value
