"""Tests for the Trump / Truth Social plugin."""

from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from jarvis.core.exceptions import PluginFetchError
from plugins.trump.plugin import (
    TrumpPlugin,
    _normalise_id,
    _parse_iso_or_rss,
    _parse_rss_feed,
    _strip_html,
)

_FIXTURES = Path(__file__).parents[3] / "plugins" / "trump" / "fixtures"


@pytest.fixture
def rss_fixture_bytes():
    return (_FIXTURES / "feed.xml").read_bytes()


@pytest.fixture
def plugin():
    return TrumpPlugin()


def test_plugin_attributes(plugin):
    assert plugin.name == "trump"
    assert plugin.display_name == "Trump / Truth Social"
    assert plugin.required_env_vars == []
    assert plugin.temperature == 0.2
    assert plugin.max_tokens == 500


def test_prompt_template_loads(plugin):
    template = plugin.prompt_template()
    assert "{{ payload }}" in template
    assert "{{ metadata }}" in template
    assert "{{ window_hours }}" in template
    assert "{{ today }}" in template


def test_redact_is_identity(plugin):
    payload = {"source": "trumpstruth.org", "post_count": 3, "posts": []}
    assert plugin.redact(payload) == payload


def test_strip_html():
    assert _strip_html("<p>Hello <b>world</b></p>") == "Hello world"
    assert _strip_html("No tags here") == "No tags here"
    assert _strip_html("  extra   spaces  ") == "extra spaces"
    assert _strip_html("") == ""


def test_normalise_id_strips_url():
    assert _normalise_id("https://www.trumpstruth.org/statuses/113456789") == "113456789"
    assert _normalise_id("113456789") == "113456789"
    assert _normalise_id("https://example.com/path/456/") == "456"


def test_parse_iso_or_rss_iso():
    dt = _parse_iso_or_rss("2026-04-23T22:41:00Z")
    assert dt is not None
    assert dt.year == 2026
    assert dt.tzinfo is not None


def test_parse_iso_or_rss_rfc2822():
    dt = _parse_iso_or_rss("Thu, 23 Apr 2026 22:41:00 +0000")
    assert dt is not None
    assert dt.year == 2026


def test_parse_iso_or_rss_empty():
    assert _parse_iso_or_rss("") is None
    assert _parse_iso_or_rss("not a date") is None


def test_parse_rss_feed_filters_old_posts(rss_fixture_bytes):
    # Only posts from the last 24h should appear; the fixture has one old post
    cutoff = datetime(2026, 4, 22, 0, 0, 0, tzinfo=UTC)
    posts = _parse_rss_feed(rss_fixture_bytes, cutoff, max_posts=50)
    assert len(posts) == 3
    ids = [p["id"] for p in posts]
    # Old post guid 112000000000001 must be excluded
    assert all("112000000000001" not in pid for pid in ids)


def test_parse_rss_feed_respects_max_posts(rss_fixture_bytes):
    cutoff = datetime(2026, 4, 22, 0, 0, 0, tzinfo=UTC)
    posts = _parse_rss_feed(rss_fixture_bytes, cutoff, max_posts=2)
    assert len(posts) == 2


def test_parse_rss_feed_sorted_newest_first(rss_fixture_bytes):
    cutoff = datetime(2026, 4, 22, 0, 0, 0, tzinfo=UTC)
    posts = _parse_rss_feed(rss_fixture_bytes, cutoff, max_posts=50)
    published_dates = [p["published"] for p in posts]
    assert published_dates == sorted(published_dates, reverse=True)


def test_parse_rss_feed_payload_shape(rss_fixture_bytes):
    cutoff = datetime(2026, 4, 22, 0, 0, 0, tzinfo=UTC)
    posts = _parse_rss_feed(rss_fixture_bytes, cutoff, max_posts=50)
    assert len(posts) > 0
    post = posts[0]
    assert "id" in post
    assert "published" in post
    assert "text" in post
    assert "url" in post
    assert "is_reply" in post
    assert "is_repost" in post
    assert "media_count" in post
    assert not post["text"].startswith("<")  # HTML stripped


async def test_fetch_returns_correct_shape(plugin, rss_fixture_bytes, monkeypatch):
    monkeypatch.setenv("TRUMP_FEED_URL", "https://www.trumpstruth.org/feed")
    monkeypatch.setenv("TRUMP_MAX_POSTS", "50")

    mock_resp = MagicMock()
    mock_resp.raise_for_status = MagicMock()
    mock_resp.content = rss_fixture_bytes

    mock_client = AsyncMock()
    mock_client.get = AsyncMock(return_value=mock_resp)
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=None)

    with patch("plugins.trump.plugin.get_authenticated_client", return_value=mock_client):
        result = await plugin.fetch(window_hours=24 * 7)  # wide window to catch fixture posts

    assert result.source_name == "Trump / Truth Social"
    payload = result.raw_payload
    assert "source" in payload
    assert "window_hours" in payload
    assert "post_count" in payload
    assert "posts" in payload
    assert payload["post_count"] == len(payload["posts"])
    assert isinstance(payload["posts"], list)


async def test_fetch_raises_on_network_error(plugin, monkeypatch):
    monkeypatch.setenv("TRUMP_FEED_URL", "https://www.trumpstruth.org/feed")

    mock_client = AsyncMock()
    mock_client.get = AsyncMock(side_effect=httpx.ConnectError("refused"))
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=None)

    with patch("plugins.trump.plugin.get_authenticated_client", return_value=mock_client):
        with pytest.raises(PluginFetchError):
            await plugin.fetch(window_hours=24)


async def test_fetch_raises_on_http_error(plugin, monkeypatch):
    monkeypatch.setenv("TRUMP_FEED_URL", "https://www.trumpstruth.org/feed")

    mock_resp = MagicMock()
    mock_resp.status_code = 503
    http_error = httpx.HTTPStatusError("503", request=MagicMock(), response=mock_resp)

    mock_client = AsyncMock()
    mock_client.get = AsyncMock(side_effect=http_error)
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=None)

    with patch("plugins.trump.plugin.get_authenticated_client", return_value=mock_client):
        with pytest.raises(PluginFetchError):
            await plugin.fetch(window_hours=24)


async def test_fetch_empty_window_returns_no_posts(plugin, rss_fixture_bytes, monkeypatch):
    monkeypatch.setenv("TRUMP_FEED_URL", "https://www.trumpstruth.org/feed")

    mock_resp = MagicMock()
    mock_resp.raise_for_status = MagicMock()
    mock_resp.content = rss_fixture_bytes

    mock_client = AsyncMock()
    mock_client.get = AsyncMock(return_value=mock_resp)
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=None)

    # 1-minute window: no posts should match
    with patch("plugins.trump.plugin.get_authenticated_client", return_value=mock_client):
        result = await plugin.fetch(window_hours=1 / 60)

    assert result.raw_payload["post_count"] == 0
    assert result.raw_payload["posts"] == []
