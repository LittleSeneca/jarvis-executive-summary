"""Trump / Truth Social data-source plugin — posts via RSS or JSON feed."""

import calendar
import json
import logging
import os
import re
from datetime import UTC, datetime, timedelta
from email.utils import parsedate_to_datetime
from urllib.parse import parse_qs, urlencode, urlparse, urlunparse

import feedparser
import httpx

from jarvis.core.exceptions import PluginFetchError
from jarvis.core.plugin import DataSourcePlugin, FetchResult

from .auth import get_authenticated_client

__all__ = ["TrumpPlugin"]

log = logging.getLogger(__name__)

_DEFAULT_FEED_URL = "https://www.trumpstruth.org/feed"
_DEFAULT_MAX_POSTS = 50
_HTML_TAG_RE = re.compile(r"<[^>]+>")
_MULTIPLE_WHITESPACE_RE = re.compile(r"\s+")


class TrumpPlugin(DataSourcePlugin):
    """Fetch @realDonaldTrump posts from Truth Social via RSS or JSON feed."""

    name = "trump"
    display_name = "Trump / Truth Social"
    required_env_vars = []
    temperature = 0.2
    max_tokens = 600

    async def fetch(self, window_hours: int) -> FetchResult:
        """Pull Truth Social posts from the last `window_hours` and return them."""
        feed_url = os.environ.get("TRUMP_FEED_URL", _DEFAULT_FEED_URL).strip() or _DEFAULT_FEED_URL
        max_posts = int(os.environ.get("TRUMP_MAX_POSTS", _DEFAULT_MAX_POSTS) or _DEFAULT_MAX_POSTS)

        cutoff = datetime.now(UTC) - timedelta(hours=window_hours)

        try:
            client = get_authenticated_client()
            async with client:
                raw_bytes = await _fetch_feed(client, feed_url, cutoff)
        except PluginFetchError:
            raise
        except httpx.RequestError as exc:
            raise PluginFetchError("Network error fetching Trump feed: %s" % exc) from exc
        except httpx.HTTPStatusError as exc:
            raise PluginFetchError(
                "HTTP %s fetching Trump feed" % exc.response.status_code
            ) from exc
        except Exception as exc:
            log.exception("Unexpected error fetching Trump feed")
            raise PluginFetchError("Unexpected error fetching Trump feed: %s" % exc) from exc

        try:
            parsed_url = urlparse(feed_url)
            suffix = parsed_url.path.lower()
            if suffix.endswith(".json"):
                posts = _parse_json_feed(raw_bytes, cutoff, max_posts)
            else:
                posts = _parse_rss_feed(raw_bytes, cutoff, max_posts)
        except Exception as exc:
            log.exception("Failed to parse Trump feed")
            raise PluginFetchError("Failed to parse Trump feed: %s" % exc) from exc

        payload = {
            "source": "trumpstruth.org",
            "window_hours": window_hours,
            "post_count": len(posts),
            "posts": posts,
        }

        log.info("Trump feed fetch complete: %d posts in last %dh", len(posts), window_hours)
        return FetchResult(
            source_name=self.display_name,
            raw_payload=payload,
            metadata={
                "feed_url": feed_url,
                "window_hours": window_hours,
                "post_count": len(posts),
                "cutoff": cutoff.isoformat(),
                "fetched_at": datetime.now(UTC).isoformat(),
            },
            links=[p["url"] for p in posts[:5] if p.get("url")],
        )


async def _fetch_feed(
    client: httpx.AsyncClient,
    feed_url: str,
    cutoff: datetime,
) -> bytes:
    """Fetch the feed URL, appending date params if it looks like an RSS feed."""
    parsed = urlparse(feed_url)
    suffix = parsed.path.lower()

    if not suffix.endswith(".json"):
        # Attempt server-side date filtering; fall back gracefully if ignored
        start_date = cutoff.strftime("%Y-%m-%d")
        end_date = datetime.now(UTC).strftime("%Y-%m-%d")
        existing_params = parse_qs(parsed.query, keep_blank_values=True)
        existing_params.setdefault("start_date", [start_date])
        existing_params.setdefault("end_date", [end_date])
        new_query = urlencode({k: v[0] for k, v in existing_params.items()})
        url_with_dates = urlunparse(parsed._replace(query=new_query))
    else:
        url_with_dates = feed_url

    resp = await client.get(url_with_dates, timeout=30.0)
    resp.raise_for_status()
    return resp.content


def _parse_rss_feed(raw: bytes, cutoff: datetime, max_posts: int) -> list[dict]:
    """Parse RSS/Atom feed bytes and return filtered, normalised post dicts."""
    feed = feedparser.parse(raw)

    posts = []
    for entry in feed.entries:
        published = _parse_rss_date(entry)
        if published is None or published < cutoff:
            continue

        text = _strip_html(entry.get("summary") or entry.get("description") or entry.get("title", ""))
        post_id = entry.get("id") or entry.get("guid") or ""
        url = entry.get("link") or ""

        # Detect reply/repost heuristics from post text prefix patterns
        is_reply = text.startswith("@")
        is_repost = text.upper().startswith("RT ") or text.startswith("♻")

        media_count = len(entry.get("media_content", [])) + len(entry.get("enclosures", []))

        posts.append({
            "id": _normalise_id(post_id),
            "published": published.isoformat(),
            "text": text,
            "url": url,
            "is_reply": is_reply,
            "is_repost": is_repost,
            "media_count": media_count,
        })

    # Sort newest-first, then cap
    posts.sort(key=lambda p: p["published"], reverse=True)
    return posts[:max_posts]


def _parse_json_feed(raw: bytes, cutoff: datetime, max_posts: int) -> list[dict]:
    """Parse a JSON feed (stiles/trump-truth-social-archive format) and return post dicts."""
    data = json.loads(raw)

    # Handle both list-at-root and {"statuses": [...]} shapes
    if isinstance(data, list):
        items = data
    elif isinstance(data, dict):
        items = data.get("statuses") or data.get("posts") or data.get("items") or []
    else:
        items = []

    posts = []
    for item in items:
        raw_date = item.get("created_at") or item.get("published") or item.get("date") or ""
        published = _parse_iso_or_rss(raw_date)
        if published is None or published < cutoff:
            continue

        text = _strip_html(item.get("content") or item.get("text") or item.get("title") or "")
        post_id = str(item.get("id") or item.get("guid") or "")
        url = item.get("url") or item.get("uri") or item.get("link") or ""

        is_reply = bool(item.get("in_reply_to_id")) or text.startswith("@")
        is_repost = bool(item.get("reblog")) or text.upper().startswith("RT ")
        media_count = len(item.get("media_attachments") or [])

        posts.append({
            "id": _normalise_id(post_id),
            "published": published.isoformat(),
            "text": text,
            "url": url,
            "is_reply": is_reply,
            "is_repost": is_repost,
            "media_count": media_count,
        })

    posts.sort(key=lambda p: p["published"], reverse=True)
    return posts[:max_posts]


def _strip_html(text: str) -> str:
    """Remove HTML tags and normalise whitespace from a string."""
    cleaned = _HTML_TAG_RE.sub(" ", text)
    return _MULTIPLE_WHITESPACE_RE.sub(" ", cleaned).strip()


def _parse_rss_date(entry) -> datetime | None:
    """Parse the published date from a feedparser entry."""
    # feedparser exposes published_parsed (struct_time) or published (string)
    if hasattr(entry, "published_parsed") and entry.published_parsed:
        ts = calendar.timegm(entry.published_parsed)
        return datetime.fromtimestamp(ts, tz=UTC)
    raw = entry.get("published") or entry.get("updated") or ""
    return _parse_iso_or_rss(raw)


def _parse_iso_or_rss(raw: str) -> datetime | None:
    """Try ISO 8601 then RFC 2822 date parsing; return None on failure."""
    if not raw:
        return None
    try:
        dt = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=UTC)
        return dt
    except ValueError:
        pass
    try:
        dt = parsedate_to_datetime(raw)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=UTC)
        return dt
    except Exception:
        return None


def _normalise_id(raw: str) -> str:
    """Strip URL prefixes from guid/id fields to return just the numeric portion."""
    # e.g. "https://www.trumpstruth.org/statuses/113456789" -> "113456789"
    return raw.rstrip("/").split("/")[-1] if "/" in raw else raw
