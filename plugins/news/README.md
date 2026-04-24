# News Plugin

Aggregates headlines from a configurable list of RSS feeds, deduplicates near-duplicate stories across outlets, and summarizes the morning's news for the executive brief.

## What it does

- Fetches all feeds listed in `NEWS_FEEDS` concurrently with a 10-second per-feed timeout.
- Each feed contributes up to `NEWS_ITEMS_PER_FEED` items published within the run window.
- When `NEWS_DEDUPE=true`, merges near-duplicate headlines across feeds (Jaccard similarity ≥ 0.6 on title token sets). A story covered by multiple outlets appears once, with all source outlets listed and `source_count > 1`.
- Items are sorted by `source_count` descending, then by recency. The LLM therefore sees the most widely-covered stories first.

## Authentication

None required. All default feeds are public RSS. `auth.py` returns an `httpx.AsyncClient` with a descriptive `User-Agent`.

## Environment variables

| Variable | Default | Description |
|---|---|---|
| `NEWS_FEEDS` | Six default feeds (BBC, CNN, Fox, NPR, Guardian, AP) | Comma-separated RSS feed URLs |
| `NEWS_ITEMS_PER_FEED` | `10` | Maximum items to pull per feed |
| `NEWS_DEDUPE` | `true` | Collapse near-duplicate headlines across feeds |

## Extending

To add a news source, append its RSS URL to `NEWS_FEEDS` in `.env`. `feedparser` handles RSS 2.0, RSS 1.0, and Atom — no code changes needed. This makes the plugin usable for any RSS-syndicated source: trade publications, SEC filings, GitHub releases, etc.

## Failures

A single feed timing out or returning an error is logged as a warning and skipped — the rest of the feeds still contribute to the digest. Only a total failure of all feeds raises `PluginFetchError`.
