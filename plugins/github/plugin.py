"""GitHub PR activity and code-volume data-source plugin."""

import logging
import os
from datetime import UTC, datetime, timedelta

import httpx

from jarvis.core.exceptions import PluginAuthError, PluginFetchError
from jarvis.core.plugin import DataSourcePlugin, FetchResult

from .auth import get_authenticated_client

__all__ = ["GitHubPlugin"]

log = logging.getLogger(__name__)

_GRAPHQL_PATH = "/graphql"

# ---------------------------------------------------------------------------
# GraphQL query definitions
# ---------------------------------------------------------------------------

_PR_QUERY = """
query PRs($newQ: String!, $closedQ: String!, $staleQ: String!) {
  new: search(query: $newQ, type: ISSUE, first: 50) {
    nodes {
      ... on PullRequest {
        number
        title
        url
        isDraft
        author { login }
        repository { nameWithOwner }
        reviewRequests(first: 10) {
          nodes {
            requestedReviewer {
              ... on User { login }
            }
          }
        }
      }
    }
  }
  closed: search(query: $closedQ, type: ISSUE, first: 50) {
    nodes {
      ... on PullRequest {
        number
        title
        url
        repository { nameWithOwner }
        merged
        mergedAt
        closedAt
        mergedBy { login }
      }
    }
  }
  stale: search(query: $staleQ, type: ISSUE, first: 50) {
    nodes {
      ... on PullRequest {
        number
        title
        url
        repository { nameWithOwner }
        updatedAt
      }
    }
  }
}
"""

_CONTRIBUTIONS_QUERY = """
query Contributions($login: String!, $from: DateTime!, $to: DateTime!) {
  user(login: $login) {
    contributionsCollection(from: $from, to: $to) {
      commitContributionsByRepository(maxRepositories: 20) {
        repository {
          nameWithOwner
          owner { login }
          name
        }
        contributions { totalCount }
      }
    }
  }
}
"""


class GitHubPlugin(DataSourcePlugin):
    """Fetch PR activity and code volume from GitHub via GraphQL."""

    name = "github"
    display_name = "GitHub"
    required_env_vars = ["GITHUB_TOKEN", "GITHUB_USER"]
    temperature = 0.2
    max_tokens = 700

    async def fetch(self, window_hours: int) -> FetchResult:
        """Pull PR buckets and yesterday's code volume from GitHub GraphQL."""
        user = os.environ.get("GITHUB_USER", "").strip()
        orgs_raw = os.environ.get("GITHUB_ORGS", "").strip()
        repos_raw = os.environ.get("GITHUB_REPOS", "").strip()
        stale_days = int(os.environ.get("GITHUB_STALE_PR_DAYS", "14"))

        if not user:
            raise PluginAuthError("GITHUB_USER is not set")

        orgs = [o.strip() for o in orgs_raw.split(",") if o.strip()] if orgs_raw else []
        repos = [r.strip() for r in repos_raw.split(",") if r.strip()] if repos_raw else []

        now_utc = datetime.now(UTC)
        window_start = now_utc - timedelta(hours=window_hours)
        stale_cutoff = now_utc - timedelta(days=stale_days)

        # Yesterday window for code volume
        yesterday_date = (now_utc - timedelta(days=1)).date()
        yesterday_from = datetime(
            yesterday_date.year, yesterday_date.month, yesterday_date.day,
            0, 0, 0, tzinfo=UTC
        )
        yesterday_to = datetime(
            yesterday_date.year, yesterday_date.month, yesterday_date.day,
            23, 59, 59, tzinfo=UTC
        )

        try:
            client = get_authenticated_client()
        except PluginAuthError:
            raise

        try:
            async with client:
                pr_payload = await _fetch_prs(
                    client, user, orgs, repos, window_start, stale_cutoff
                )
                code_volume = await _fetch_code_volume(
                    client, user, yesterday_from, yesterday_to
                )
        except PluginAuthError:
            raise
        except PluginFetchError:
            raise
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code in (401, 403):
                raise PluginAuthError(
                    "GitHub rejected credentials (HTTP %s)" % exc.response.status_code
                ) from exc
            raise PluginFetchError(
                "GitHub API HTTP error %s" % exc.response.status_code
            ) from exc
        except httpx.RequestError as exc:
            raise PluginFetchError("Network error reaching GitHub: %s" % exc) from exc
        except Exception as exc:
            log.exception("Unexpected error in GitHub fetch")
            raise PluginFetchError("Unexpected error in GitHub fetch: %s" % exc) from exc

        payload = {
            "window_hours": window_hours,
            "user": user,
            "prs": pr_payload,
            "code_volume_yesterday": code_volume,
        }

        log.info(
            "GitHub fetch complete: %d new PRs, %d closed, %d stale; "
            "%d commits yesterday (+%d/-%d)",
            len(pr_payload["new"]),
            len(pr_payload["closed"]),
            len(pr_payload["stale"]),
            code_volume["commits"],
            code_volume["additions"],
            code_volume["deletions"],
        )
        return FetchResult(
            source_name=self.display_name,
            raw_payload=payload,
            metadata={
                "user": user,
                "orgs": orgs,
                "window_hours": window_hours,
                "stale_pr_days": stale_days,
                "fetched_at": now_utc.isoformat(),
            },
            links=[],
        )


# ---------------------------------------------------------------------------
# GraphQL helper
# ---------------------------------------------------------------------------

async def _graphql(
    client: httpx.AsyncClient, query: str, variables: dict
) -> dict:
    """POST a GraphQL query and return the `data` dict, or raise PluginFetchError."""
    resp = await client.post(_GRAPHQL_PATH, json={"query": query, "variables": variables})

    if resp.status_code == 403:
        body = resp.text
        if "rate limit" in body.lower():
            raise PluginFetchError("GitHub GraphQL rate limit exceeded (HTTP 403)")
        raise PluginAuthError("GitHub rejected credentials (HTTP 403)")

    resp.raise_for_status()

    body = resp.json()
    if "errors" in body:
        errors = body["errors"]
        first_msg = errors[0].get("message", str(errors[0])) if errors else "unknown"
        if "rate limit" in first_msg.lower():
            raise PluginFetchError("GitHub GraphQL rate limit: %s" % first_msg)
        raise PluginFetchError("GitHub GraphQL error: %s" % first_msg)

    return body.get("data", {})


# ---------------------------------------------------------------------------
# PR fetching
# ---------------------------------------------------------------------------

async def _fetch_prs(
    client: httpx.AsyncClient,
    user: str,
    orgs: list[str],
    repos: list[str],
    window_start: datetime,
    stale_cutoff: datetime,
) -> dict:
    """Fetch new, closed, and stale PRs in a single GraphQL round-trip."""
    window_str = window_start.strftime("%Y-%m-%d")
    stale_str = stale_cutoff.strftime("%Y-%m-%d")

    scope = _build_scope(orgs, repos)

    new_q = "is:pr is:open created:>=%s %s" % (window_str, scope)
    closed_q = "is:pr is:closed closed:>=%s %s" % (window_str, scope)
    stale_q = "is:pr is:open updated:<=%s %s" % (stale_str, scope)

    data = await _graphql(
        client,
        _PR_QUERY,
        {"newQ": new_q, "closedQ": closed_q, "staleQ": stale_q},
    )

    now_utc = datetime.now(UTC)
    new_prs = _parse_new_prs(data.get("new", {}).get("nodes", []))
    closed_prs = _parse_closed_prs(data.get("closed", {}).get("nodes", []))
    stale_prs = _parse_stale_prs(data.get("stale", {}).get("nodes", []), now_utc)

    return {"new": new_prs, "closed": closed_prs, "stale": stale_prs}


def _build_scope(orgs: list[str], repos: list[str]) -> str:
    """Build the search-scope fragment from orgs and/or repos."""
    parts: list[str] = []
    for org in orgs:
        parts.append("org:%s" % org)
    for repo in repos:
        parts.append("repo:%s" % repo)
    return " ".join(parts)


def _parse_new_prs(nodes: list[dict]) -> list[dict]:
    result = []
    for node in nodes:
        if not node:
            continue
        reviewers = [
            rr["requestedReviewer"]["login"]
            for rr in node.get("reviewRequests", {}).get("nodes", [])
            if rr.get("requestedReviewer") and "login" in rr["requestedReviewer"]
        ]
        result.append({
            "repo": node.get("repository", {}).get("nameWithOwner", ""),
            "number": node.get("number"),
            "title": node.get("title", ""),
            "author": (node.get("author") or {}).get("login", ""),
            "url": node.get("url", ""),
            "draft": node.get("isDraft", False),
            "reviewers": reviewers,
        })
    return result


def _parse_closed_prs(nodes: list[dict]) -> list[dict]:
    result = []
    for node in nodes:
        if not node:
            continue
        result.append({
            "repo": node.get("repository", {}).get("nameWithOwner", ""),
            "number": node.get("number"),
            "title": node.get("title", ""),
            "merged": node.get("merged", False),
            "merged_by": (node.get("mergedBy") or {}).get("login", ""),
            "url": node.get("url", ""),
        })
    return result


def _parse_stale_prs(nodes: list[dict], now_utc: datetime) -> list[dict]:
    result = []
    for node in nodes:
        if not node:
            continue
        updated_at_str = node.get("updatedAt", "")
        days_since = None
        if updated_at_str:
            try:
                updated_at = datetime.fromisoformat(updated_at_str.replace("Z", "+00:00"))
                days_since = (now_utc - updated_at).days
            except ValueError:
                pass
        result.append({
            "repo": node.get("repository", {}).get("nameWithOwner", ""),
            "number": node.get("number"),
            "title": node.get("title", ""),
            "days_since_update": days_since,
            "url": node.get("url", ""),
        })
    # Sort longest-stale first
    result.sort(key=lambda x: x.get("days_since_update") or 0, reverse=True)
    return result


# ---------------------------------------------------------------------------
# Code volume fetching
# ---------------------------------------------------------------------------

async def _fetch_code_volume(
    client: httpx.AsyncClient,
    user: str,
    from_dt: datetime,
    to_dt: datetime,
) -> dict:
    """Fetch yesterday's commit additions/deletions for user via two GraphQL steps."""
    yesterday_str = from_dt.date().isoformat()

    # Step A: discover repos the user committed to yesterday
    data = await _graphql(
        client,
        _CONTRIBUTIONS_QUERY,
        {
            "login": user,
            "from": from_dt.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "to": to_dt.strftime("%Y-%m-%dT%H:%M:%SZ"),
        },
    )

    contributions_data = (
        data.get("user") or {}
    ).get("contributionsCollection", {})
    repos_with_commits = contributions_data.get("commitContributionsByRepository", [])

    if not repos_with_commits:
        log.info("No commit contributions found for %s on %s", user, yesterday_str)
        return {
            "date": yesterday_str,
            "commits": 0,
            "repos_touched": [],
            "additions": 0,
            "deletions": 0,
            "net": 0,
        }

    # Step B: fetch commit history (additions/deletions) for each repo
    repo_list = [
        (entry["repository"]["owner"]["login"], entry["repository"]["name"])
        for entry in repos_with_commits
        if entry.get("repository")
    ]

    volume_data = await _fetch_repo_commit_stats(client, repo_list, from_dt, to_dt)

    total_additions = sum(r["additions"] for r in volume_data)
    total_deletions = sum(r["deletions"] for r in volume_data)
    total_commits = sum(r["commits"] for r in volume_data)
    repos_touched = [r["repo"] for r in volume_data if r["commits"] > 0]

    return {
        "date": yesterday_str,
        "commits": total_commits,
        "repos_touched": repos_touched,
        "additions": total_additions,
        "deletions": total_deletions,
        "net": total_additions - total_deletions,
    }


async def _fetch_repo_commit_stats(
    client: httpx.AsyncClient,
    repo_list: list[tuple[str, str]],
    from_dt: datetime,
    to_dt: datetime,
) -> list[dict]:
    """Build a single aliased GraphQL query to get commit stats for all repos."""
    since = from_dt.strftime("%Y-%m-%dT%H:%M:%SZ")
    until = to_dt.strftime("%Y-%m-%dT%H:%M:%SZ")

    # Build aliased per-repo sub-queries
    sub_queries: list[str] = []
    for idx, (owner, name) in enumerate(repo_list):
        alias = "r%d" % idx
        sub_queries.append(
            """  %s: repository(owner: "%s", name: "%s") {
    defaultBranchRef {
      target {
        ... on Commit {
          history(since: "%s", until: "%s") {
            nodes { additions deletions }
          }
        }
      }
    }
  }"""
            % (alias, owner, name, since, until)
        )

    if not sub_queries:
        return []

    query = "query CodeVolume {\n%s\n}" % "\n".join(sub_queries)

    data = await _graphql(client, query, {})

    results: list[dict] = []
    for idx, (owner, name) in enumerate(repo_list):
        alias = "r%d" % idx
        repo_name = "%s/%s" % (owner, name)
        repo_data = data.get(alias) or {}
        default_ref = repo_data.get("defaultBranchRef") or {}
        target = default_ref.get("target") or {}
        history_nodes = (target.get("history") or {}).get("nodes", [])

        additions = sum(n.get("additions", 0) for n in history_nodes)
        deletions = sum(n.get("deletions", 0) for n in history_nodes)
        commits = len(history_nodes)

        results.append({
            "repo": repo_name,
            "commits": commits,
            "additions": additions,
            "deletions": deletions,
        })

    return results
