"""Gmail data-source plugin — inbox summary for the last N hours."""

import asyncio
import logging
import os
import re
from datetime import UTC, datetime
from typing import Any

import httpx

from jarvis.core.exceptions import PluginAuthError, PluginFetchError
from jarvis.core.plugin import DataSourcePlugin, FetchResult

from .auth import get_authenticated_client

__all__ = ["GmailPlugin"]

log = logging.getLogger(__name__)

_BATCH_SIZE = 20
_MAX_MESSAGES = 100
_SNIPPET_MAX = 500

# Match a full email address — keep display name + domain, strip local part
_EMAIL_LOCAL_RE = re.compile(r"([^<]+<)[^@]+(@[^>]+>)")


class GmailPlugin(DataSourcePlugin):
    """Fetch the last window_hours of Gmail inbox messages."""

    name = "gmail"
    display_name = "Gmail"
    required_env_vars = [
        "GMAIL_CLIENT_ID",
        "GMAIL_CLIENT_SECRET",
        "GMAIL_REFRESH_TOKEN",
        "GMAIL_USER",
    ]
    temperature = 0.3
    max_tokens = 800

    async def fetch(self, window_hours: int) -> FetchResult:
        """Pull inbox messages from the last window_hours."""
        user = os.environ.get("GMAIL_USER", "").strip()
        if not user:
            raise PluginAuthError("GMAIL_USER is not set")

        query = os.environ.get("GMAIL_QUERY", "in:inbox newer_than:1d").strip() or "in:inbox newer_than:1d"

        try:
            client = await get_authenticated_client()
        except PluginAuthError:
            raise

        try:
            async with client:
                message_ids = await _list_messages(client, user, query)
                messages = await _fetch_messages_batched(client, user, message_ids)
        except PluginAuthError:
            raise
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code == 401:
                raise PluginAuthError("Gmail rejected credentials (401)") from exc
            raise PluginFetchError(
                "Gmail API HTTP error %s" % exc.response.status_code
            ) from exc
        except httpx.RequestError as exc:
            raise PluginFetchError("Network error reaching Gmail API: %s" % exc) from exc
        except Exception as exc:
            log.exception("Unexpected error in Gmail fetch")
            raise PluginFetchError("Unexpected error in Gmail fetch: %s" % exc) from exc

        payload = {
            "window_hours": window_hours,
            "message_count": len(messages),
            "messages": messages,
        }

        log.info("Gmail fetch complete: %d messages for %s", len(messages), user)
        return FetchResult(
            source_name=self.display_name,
            raw_payload=payload,
            metadata={
                "window_hours": window_hours,
                "user": user,
                "message_count": len(messages),
                "query": query,
                "fetched_at": datetime.now(UTC).isoformat(),
            },
        )

    def redact(self, payload: Any) -> Any:
        """Strip local parts of email addresses; truncate snippets."""
        import copy

        redacted = copy.deepcopy(payload)
        for msg in redacted.get("messages", []):
            if msg.get("from"):
                msg["from"] = _redact_email(msg["from"])
            if msg.get("snippet") and len(msg["snippet"]) > _SNIPPET_MAX:
                msg["snippet"] = msg["snippet"][:_SNIPPET_MAX]
        return redacted


async def _list_messages(
    client: httpx.AsyncClient, user: str, query: str
) -> list[str]:
    """Return up to _MAX_MESSAGES message IDs matching query."""
    resp = await client.get(
        "/gmail/v1/users/%s/messages" % user,
        params={"q": query, "maxResults": _MAX_MESSAGES},
    )
    if resp.status_code == 401:
        raise PluginAuthError("Gmail rejected credentials (401) listing messages")
    resp.raise_for_status()
    data = resp.json()
    return [m["id"] for m in data.get("messages", [])]


async def _fetch_messages_batched(
    client: httpx.AsyncClient, user: str, message_ids: list[str]
) -> list[dict]:
    """Fetch message metadata in batches of _BATCH_SIZE via asyncio.gather."""
    results: list[dict] = []
    for i in range(0, len(message_ids), _BATCH_SIZE):
        batch_ids = message_ids[i : i + _BATCH_SIZE]
        batch = await asyncio.gather(
            *[_fetch_message(client, user, mid) for mid in batch_ids]
        )
        results.extend(m for m in batch if m is not None)
    return results


async def _fetch_message(
    client: httpx.AsyncClient, user: str, message_id: str
) -> dict | None:
    """Fetch metadata + snippet for a single message."""
    resp = await client.get(
        "/gmail/v1/users/%s/messages/%s" % (user, message_id),
        params={
            "format": "metadata",
            "metadataHeaders": ["From", "To", "Subject", "Date"],
        },
    )
    if resp.status_code == 401:
        raise PluginAuthError("Gmail rejected credentials (401) fetching message %s" % message_id)
    resp.raise_for_status()
    data = resp.json()

    headers = {h["name"]: h["value"] for h in data.get("payload", {}).get("headers", [])}
    label_ids = data.get("labelIds", [])
    parts = data.get("payload", {}).get("parts", [])

    snippet = data.get("snippet", "")
    if len(snippet) > _SNIPPET_MAX:
        snippet = snippet[:_SNIPPET_MAX]

    return {
        "id": data.get("id", ""),
        "thread_id": data.get("threadId", ""),
        "subject": headers.get("Subject", "(no subject)"),
        "from": headers.get("From", ""),
        "to": headers.get("To", ""),
        "snippet": snippet,
        "date": headers.get("Date", ""),
        "is_unread": "UNREAD" in label_ids,
        "has_attachments": _has_attachments(parts),
    }


def _has_attachments(parts: list[dict]) -> bool:
    """Return True if any part has a non-empty filename (i.e., is an attachment)."""
    for part in parts:
        if part.get("filename"):
            return True
        sub = part.get("parts", [])
        if sub and _has_attachments(sub):
            return True
    return False


def _redact_email(value: str) -> str:
    """Replace the local part of email addresses with '...'."""
    return _EMAIL_LOCAL_RE.sub(r"\1...\2", value)
