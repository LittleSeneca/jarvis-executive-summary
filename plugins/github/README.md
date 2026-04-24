# GitHub Plugin

Fetches PR activity across configured orgs and the user's code volume from yesterday, using GitHub's GraphQL API exclusively (no REST calls).

## Required credentials

| Env var | Description |
|---------|-------------|
| `GITHUB_TOKEN` | Personal access token with `repo` + `read:org` scopes |
| `GITHUB_USER` | GitHub username to report on (e.g. `GrahamBrooks`) |

## Optional configuration

| Env var | Default | Description |
|---------|---------|-------------|
| `GITHUB_ORGS` | _(none)_ | Comma-separated org names to scope PR searches |
| `GITHUB_REPOS` | _(none)_ | Comma-separated `owner/repo` overrides to restrict scope further |
| `GITHUB_STALE_PR_DAYS` | `14` | PRs open with no update for this many days are counted as stale |

## What it fetches

**Query 1 — PR buckets (one GraphQL round-trip, three aliased searches):**

| Bucket | Search criteria |
|--------|----------------|
| New | `is:pr is:open created:>=<window_start>` |
| Closed | `is:pr is:closed closed:>=<window_start>` |
| Stale | `is:pr is:open updated:<=<stale_cutoff>` |

Each bucket is capped at 50 results.

**Query 2 — code volume (two steps):**

1. `contributionsCollection` to find repos `GITHUB_USER` committed to yesterday
2. A single aliased GraphQL request fetching commit `additions`/`deletions` for each repo on the default branch within yesterday's window

Total API cost: 2–3 GraphQL requests per run (PR buckets + contributions + aliased history batch if repos were found).

## Payload shape

```json
{
  "window_hours": 24,
  "user": "GrahamBrooks",
  "prs": {
    "new": [{ "repo": "...", "number": 42, "title": "...", "author": "...", "url": "...", "draft": false, "reviewers": [] }],
    "closed": [{ "repo": "...", "number": 39, "title": "...", "merged": true, "merged_by": "...", "url": "..." }],
    "stale": [{ "repo": "...", "number": 27, "days_since_update": 23, "title": "...", "url": "..." }]
  },
  "code_volume_yesterday": {
    "date": "2026-04-22",
    "commits": 11,
    "repos_touched": ["littleseneca/jarvis-executive-summary"],
    "additions": 412,
    "deletions": 178,
    "net": 234
  }
}
```

## Redaction

Nothing redacted by default — PR titles, numbers, and URLs are already public within the org.

## Token requirements

The PAT needs:
- `repo` — read access to private repositories
- `read:org` — enumerate org-scoped PRs

No write scopes are required or used.
