# Trump / Truth Social Plugin

Fetches posts from @realDonaldTrump on Truth Social via a public RSS or JSON feed and summarizes them neutrally in the morning brief.

## Credentials

None required. The feed is public.

| Env var | Required | Default | Notes |
|---------|----------|---------|-------|
| `TRUMP_FEED_URL` | No | `https://www.trumpstruth.org/feed` | RSS or JSON URL |
| `TRUMP_MAX_POSTS` | No | `50` | Cap on posts per run |

## Feed sources

**Primary (default):** `https://www.trumpstruth.org/feed` — RSS 2.0 served by an independent archive site. Supports `?start_date=YYYY-MM-DD&end_date=YYYY-MM-DD` for server-side filtering. No API key, no authentication.

**Fallback:** Point `TRUMP_FEED_URL` at the raw JSON from the [stiles/trump-truth-social-archive](https://github.com/stiles/trump-truth-social-archive) GitHub repository (updated every few minutes). The plugin detects `.json` URLs and parses accordingly.

## Feed format detection

The plugin dispatches on URL suffix:
- `.xml` / `.rss` / anything else → parsed as RSS with `feedparser`
- `.json` → parsed as JSON (handles both list-at-root and `{"statuses": [...]}` shapes)

## Payload shape

```json
{
  "source": "trumpstruth.org",
  "window_hours": 24,
  "post_count": 14,
  "posts": [
    {
      "id": "113456789",
      "published": "2026-04-22T23:41:00+00:00",
      "text": "Post text with HTML decoded, @mentions and #hashtags preserved.",
      "url": "https://www.trumpstruth.org/statuses/113456789",
      "is_reply": false,
      "is_repost": false,
      "media_count": 0
    }
  ]
}
```

## Political sensitivity

This plugin reports opinion content from a political figure. The prompt is written to describe, not interpret. If this section is not useful, remove `trump` from `ENABLED_PLUGINS`.

## Notes

- Trump can post prolifically overnight. `TRUMP_MAX_POSTS=50` caps the payload; adjust down to reduce token usage or up to capture high-volume periods.
- The trumpstruth.org site has no SLA. If it goes down, the plugin fails gracefully — the rest of the brief still posts.
- HTML tags are stripped from post text before the payload is forwarded to the LLM.
