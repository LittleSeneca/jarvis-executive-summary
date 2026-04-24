"""News plugin — parallel RSS fetch with cross-feed deduplication."""

import asyncio
import calendar
import html
import logging
import os
import re
from datetime import UTC, datetime, timedelta
from email.utils import parsedate_to_datetime
from typing import Any

import feedparser
import httpx

from jarvis.core.exceptions import PluginFetchError
from jarvis.core.plugin import DataSourcePlugin, FetchResult

from .auth import get_authenticated_client

__all__ = ["NewsPlugin"]

log = logging.getLogger(__name__)

_DEFAULT_FEEDS = (
    "https://feeds.bbci.co.uk/news/world/rss.xml,"
    "http://rss.cnn.com/rss/cnn_topstories.rss,"
    "https://moxie.foxnews.com/google-publisher/us.xml,"
    "https://feeds.npr.org/1001/rss.xml,"
    "https://www.theguardian.com/international/rss,"
    "https://apnews.com/index.rss"
)
_JACCARD_THRESHOLD = 0.6
_PUNCT_RE = re.compile(r"[^\w\s]")


def _parse_feed_urls() -> list[str]:
    raw = os.environ.get("NEWS_FEEDS", _DEFAULT_FEEDS)
    return [u.strip() for u in raw.split(",") if u.strip()]


def _items_per_feed() -> int:
    try:
        return int(os.environ.get("NEWS_ITEMS_PER_FEED", "10"))
    except ValueError:
        return 10


def _dedupe_enabled() -> bool:
    return os.environ.get("NEWS_DEDUPE", "true").lower() not in {"false", "0", "no"}


def _strip_html(text: str) -> str:
    """Strip HTML tags and decode HTML entities from a string."""
    text = re.sub(r"<[^>]+>", " ", text)
    text = html.unescape(text)
    return " ".join(text.split())


def _normalize_title(title: str) -> set[str]:
    """Lowercase, remove punctuation, return token set."""
    lower = title.lower()
    no_punct = _PUNCT_RE.sub(" ", lower)
    return set(no_punct.split())


def _jaccard(a: set[str], b: set[str]) -> float:
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


def _parse_published(entry: Any) -> datetime | None:
    """Parse published/updated date from a feedparser entry."""
    for attr in ("published", "updated", "created"):
        raw = getattr(entry, attr, None)
        if raw:
            try:
                return parsedate_to_datetime(raw).astimezone(UTC).replace(tzinfo=UTC)
            except Exception:
                pass
    # feedparser also populates *_parsed tuples
    for attr in ("published_parsed", "updated_parsed"):
        parsed = getattr(entry, attr, None)
        if parsed:
            try:
                ts = calendar.timegm(parsed)
                return datetime.fromtimestamp(ts, tz=UTC)
            except Exception:
                pass
    return None


async def _fetch_feed(
    client: httpx.AsyncClient,
    url: str,
    window_hours: int,
    items_per_feed: int,
) -> list[dict]:
    """Fetch and parse a single RSS feed, returning items within the window."""
    cutoff = datetime.now(tz=UTC) - timedelta(hours=window_hours)
    outlet_name = url  # fallback; overwritten after parse

    try:
        response = await client.get(url)
        response.raise_for_status()
    except httpx.TimeoutException:
        log.warning("Timeout fetching feed: %s", url)
        return []
    except httpx.HTTPStatusError as exc:
        log.warning("HTTP %s fetching feed %s: %s", exc.response.status_code, url, exc)
        return []
    except Exception as exc:
        log.warning("Error fetching feed %s: %s", url, exc)
        return []

    try:
        parsed = feedparser.parse(response.text)
    except Exception as exc:
        log.warning("feedparser failed on %s: %s", url, exc)
        return []

    outlet_name = parsed.feed.get("title", url)

    items: list[dict] = []
    for entry in parsed.entries:
        if len(items) >= items_per_feed:
            break

        published = _parse_published(entry)
        # If no date, include the item (we cannot filter it out)
        if published and published < cutoff:
            continue

        title = _strip_html(getattr(entry, "title", ""))
        if not title:
            continue

        summary_raw = getattr(entry, "summary", "") or getattr(entry, "description", "")
        summary = _strip_html(summary_raw)[:500]  # cap summary length

        link = getattr(entry, "link", "")

        items.append(
            {
                "title": title,
                "summary": summary,
                "published": published.isoformat() if published else None,
                "sources": [{"outlet": outlet_name, "url": link}],
                "source_count": 1,
                "_tokens": _normalize_title(title),
            }
        )

    log.debug("Feed %s produced %d items", url, len(items))
    return items


def _deduplicate(all_items: list[dict]) -> list[dict]:
    """Merge near-duplicate items across feeds using Jaccard title similarity."""
    merged: list[dict] = []

    for item in all_items:
        tokens = item["_tokens"]
        found = False
        for existing in merged:
            if _jaccard(tokens, existing["_tokens"]) >= _JACCARD_THRESHOLD:
                # Merge sources; pick the earlier published date
                existing["sources"].extend(item["sources"])
                existing["source_count"] = len(existing["sources"])
                if item["published"] and existing["published"]:
                    if item["published"] < existing["published"]:
                        existing["published"] = item["published"]
                elif item["published"]:
                    existing["published"] = item["published"]
                found = True
                break
        if not found:
            merged.append(dict(item))  # shallow copy so we can mutate

    return merged


def _clean_item(item: dict) -> dict:
    """Strip internal fields before including in the payload."""
    return {
        "title": item["title"],
        "summary": item["summary"],
        "published": item["published"],
        "sources": item["sources"],
        "source_count": item["source_count"],
    }


class NewsPlugin(DataSourcePlugin):
    """Aggregate headlines from configurable RSS feeds."""

    name = "news"
    display_name = "News"
    required_env_vars: list[str] = []
    temperature = 0.2
    max_tokens = 800

    async def fetch(self, window_hours: int) -> FetchResult:
        """Fetch headlines from all configured RSS feeds in parallel."""
        feed_urls = _parse_feed_urls()
        items_per_feed = _items_per_feed()
        dedupe = _dedupe_enabled()

        log.info(
            "Fetching %d RSS feeds (window=%dh, items_per_feed=%d, dedupe=%s)",
            len(feed_urls),
            window_hours,
            items_per_feed,
            dedupe,
        )

        try:
            async with get_authenticated_client() as client:
                tasks = [
                    _fetch_feed(client, url, window_hours, items_per_feed)
                    for url in feed_urls
                ]
                results = await asyncio.gather(*tasks, return_exceptions=False)
        except Exception as exc:
            log.exception("Unexpected error during news fetch")
            raise PluginFetchError(f"News fetch failed: {exc}") from exc

        all_items: list[dict] = []
        for feed_items in results:
            all_items.extend(feed_items)

        log.info("Collected %d raw items across %d feeds", len(all_items), len(feed_urls))

        if dedupe:
            all_items = _deduplicate(all_items)
            log.info("After deduplication: %d items", len(all_items))

        # Sort: most-covered first, then most-recent
        all_items.sort(
            key=lambda i: (
                -i["source_count"],
                # Convert None published to epoch so sort stays stable
                -(
                    datetime.fromisoformat(i["published"]).timestamp()
                    if i["published"]
                    else 0
                ),
            )
        )

        payload = {
            "window_hours": window_hours,
            "feed_count": len(feed_urls),
            "items": [_clean_item(i) for i in all_items],
        }

        links = [
            s["url"]
            for item in all_items[:5]
            for s in item["sources"]
            if s.get("url")
        ]

        return FetchResult(
            source_name=self.display_name,
            raw_payload=payload,
            metadata={
                "feed_count": len(feed_urls),
                "item_count": len(all_items),
                "window_hours": window_hours,
                "dedupe": dedupe,
            },
            links=links[:10],
        )

    def redact(self, payload: Any) -> Any:
        """No redaction required — RSS headlines are public content."""
        return payload
