# Jarvis — Executive Summary Agent

**Status:** Draft v0.3
**Owner:** Graham Brooks
**Last updated:** 2026-04-23

---

## 1. Purpose

Jarvis is a containerized Python service that performs a single one-shot run: when the container is started, it pulls the last 24 hours of activity from a configurable set of data sources (Site24x7, AWS SecurityHub, AWS Billing, Drata, Gmail, GitHub, local weather, multi-source news headlines, stock movements on a watchlist, and Trump's Truth Social posts to start), runs each source's raw payload through Groq-hosted LLM inference with a source-specific prompt, posts a single consolidated executive-brief message to Slack, and exits.

The core design principle is that **each data source is a self-contained plugin**. Plugins own their own payload schema, prompt, and inference parameters (including Groq temperature). Adding a new source means dropping a new Python module into the plugins directory and adding credentials to the `.env` file — no changes to the core loop.

Scheduling is deliberately out of scope. Jarvis does not run a loop, does not sleep, and does not know what time it is. The container is invoked externally (by any mechanism the operator chooses); it executes its plugin list once, in order, and terminates.

### Success criteria

- Starting the container produces one well-formatted Slack digest that summarizes what happened overnight across every enabled source, then the process exits cleanly.
- Adding a new data source takes under an hour: write a plugin module, define its payload and prompt, add env vars, run the container.
- Plugins own their own payload schema. The core has no opinion about what shape a fetch returns — it receives an opaque JSON-serializable blob and hands it to the plugin's prompt.
- The service is credential-portable — everything configurable lives in `.env`, no hard-coded secrets or org-specific values in code.
- A failure in one plugin (e.g., Drata API is down) does not break the digest; other sources still report and the failed source is noted.

### Non-goals (v1)

- Real-time alerting. Jarvis is a digest, not a pager.
- Two-way interaction. Jarvis posts; it does not take Slack commands in v1.
- Historical storage. Each run is independent; no database of past digests.
- Multi-user / multi-tenant. Jarvis runs for one person.

---

## 2. High-level architecture

```
+------------------------------------------------------------------+
|                        Jarvis Container                           |
|                  (starts, runs once, exits)                       |
|                                                                   |
|   +----------------+     +-----------------+    +-------------+   |
|   | Plugin Loader  | --> |  Orchestrator   | -> |  Groq Queue |   |
|   | (auto-discover)|     |  (run-once)     |    |  (rate-lim) |   |
|   +----------------+     +--------+--------+    +------+------+   |
|          ^                        |                    |          |
|          |                        v                    v          |
|   +------+------+        +--------+---------+   +------+------+   |
|   |  plugins/   |        |  Per-plugin      |   |   Groq API  |   |
|   |  site24x7   |        |  fetch -> raw    |   |  (external) |   |
|   |  securityhub|        |  payload         |   +------+------+   |
|   |  aws_billing|        |  (plugin-defined)|          |          |
|   |  drata      |        +--------+---------+          v          |
|   |  gmail      |                 |           +--------+------+   |
|   |  github     |                 +---------> | Summarizer    |   |
|   |  weather    |                             | (prompt + LLM)|   |
|   |  news       |                             +--------+------+   |
|   |  stocks     |                                                 |
|   |  trump      |                                                 |
|   +-------------+                                                 |
|                                                        |          |
|                                                        v          |
|                                               +--------+------+   |
|                                               | Slack Formatter|  |
|                                               | + Delivery     |  |
|                                               +--------+-------+  |
+--------------------------------------------------------+----------+
                                                         |
                                                         v
                                                 +---------------+
                                                 |  Slack (user  |
                                                 |  DM or channel)|
                                                 +---------------+
```

### Flow in one sentence

On container start, the orchestrator discovers and invokes every enabled plugin, each plugin returns a raw payload (whose schema the plugin itself defines) plus metadata, the summarizer submits each payload through a rate-limited queue to Groq with a plugin-specific prompt and temperature, results are merged into a single Slack Block Kit message, the message is posted, and the process exits.

---

## 3. Core components

### 3.1 Plugin Loader

- Scans `plugins/` at startup.
- Any module that defines a class implementing the `DataSourcePlugin` interface (§5) and is listed in `ENABLED_PLUGINS` in `.env` is registered.
- Plugins not listed in `ENABLED_PLUGINS` are skipped — the file can exist without being active.
- Loader validates that each enabled plugin's required env vars are present; missing creds = hard fail with a clear error before any network calls.

### 3.2 Orchestrator

- Entry point of the container.
- Executes plugins concurrently (`asyncio.gather`) with a per-plugin timeout (default 60s, overridable per plugin).
- Collects results into a `RunReport` containing: per-plugin raw payloads, per-plugin status (ok / timeout / error + message), start/end timestamps.
- Passes the `RunReport` to the summarization layer.
- If every plugin fails, still posts a message to Slack reporting the outage (so silence never means "Jarvis is broken and I don't know").

### 3.3 Groq inference queue

Groq's API has per-minute token and request rate limits. A naive "call Groq once per plugin in parallel" approach will trip those limits on large payloads (SecurityHub findings can be tens of thousands of tokens). The queue exists to solve that, not to be a generic distributed job queue.

**Design:**

- An in-process `asyncio.Queue` holds `InferenceJob` objects (prompt + payload + plugin name + max_tokens).
- A small pool of worker coroutines (default 2) pulls from the queue and calls Groq.
- A token-bucket rate limiter sits in front of the API call, configured from `.env` (`GROQ_REQUESTS_PER_MINUTE`, `GROQ_TOKENS_PER_MINUTE`).
- On rate-limit (429) response, worker backs off exponentially and re-enqueues.
- On payload too large for model context, the summarizer pre-chunks (§3.4) before enqueueing.
- All workers complete before the orchestrator proceeds to Slack formatting.

No external broker (Redis, SQS, RabbitMQ). The queue is in-memory because the whole run is short-lived and single-process. If throughput ever outgrows this, the queue interface is narrow enough to swap in a real broker without touching plugins.

### 3.4 Summarizer

For each plugin's raw payload:

1. Call `plugin.redact(payload)` to let the plugin strip anything it doesn't want sent to Groq (§5.3). All downstream steps see only the redacted payload.
2. Load the plugin's prompt template from `plugins/<name>/prompt.md`.
3. Estimate token count. If payload + prompt exceeds the model's context window:
   - **Map-reduce strategy:** split payload into chunks, summarize each chunk, then summarize the summaries.
   - Chunking strategy is pluggable per plugin — the default is "split on top-level JSON array elements," since most source payloads are lists of findings/events/emails. A plugin that returns a non-list payload can override with its own chunker.
4. Submit the final `InferenceJob` to the Groq queue, tagged with the plugin's declared `temperature` and (optionally) `model_override` and `max_tokens`.
5. Receive structured output: a short markdown block the plugin author wrote the prompt to produce (headline + 3–7 bullets + risk/attention flags).

**Groq model:** a global default is set via `GROQ_MODEL` env var (suggested: `llama-3.3-70b-versatile`). Individual plugins may override this by setting a `model_override` class attribute — e.g., a plugin returning very small payloads might pick a faster/cheaper model.

**Temperature is plugin-owned.** Each plugin declares its own `temperature` (a float, typically 0.0–0.4 for factual summarization). This is part of the plugin contract (§5) rather than global config, because the right temperature depends on what the plugin is summarizing — deterministic bullet extraction from SecurityHub vs. slightly looser paraphrasing of email context warrant different settings.

**Output contract** each plugin summary must conform to:

```markdown
### <Source Name>
_<one-line headline>_

- <bullet 1>
- <bullet 2>
- ...

**Attention:** <optional, only if something needs the user's eyes today>
```

This contract is enforced by the prompt, not by code parsing — Groq returns markdown that's already in the right shape.

### 3.5 Slack Formatter & Delivery

- Takes all per-plugin summary blocks and assembles one Slack message using Block Kit.
- Structure:
  - **Header:** "Jarvis — Morning Brief — <date>"
  - **Context block:** run duration, plugins succeeded / failed
  - **One section per plugin** containing that plugin's markdown summary
  - **Divider** between sections
  - **Footer context:** "Generated by Groq · <model> · <tokens used>"
- Posts via Slack Web API (`chat.postMessage`) using a bot token (`SLACK_BOT_TOKEN`).
- Destination is explicitly typed via two env vars:
  - `SLACK_TARGET_TYPE` — either `channel` or `user`
  - `SLACK_TARGET_ID` — the Slack ID of the channel or user (e.g. `C0XXXXXXX` for a channel, `U0XXXXXXX` for a user DM)
  - When `SLACK_TARGET_TYPE=user`, Jarvis opens (or reuses) a DM conversation with that user via `conversations.open` and posts there. When `channel`, it posts directly to the channel ID.
- Message is a single post, not a thread.
- On Slack API failure, falls back to writing the full digest to stdout (container logs) so the run isn't lost.

---

## 4. Configuration — `.env`

All configuration lives in a single `.env` file mounted into the container. No YAML, no config server, no secrets manager integration in v1.

### Core vars

```
# --- Core ---
ENABLED_PLUGINS=site24x7,securityhub,aws_billing,drata,gmail,github,weather,news,stocks,trump
LOG_LEVEL=INFO
RUN_WINDOW_HOURS=24                 # how far back each plugin should look

# --- Groq ---
GROQ_API_KEY=gsk_...
GROQ_MODEL=llama-3.3-70b-versatile   # default model; plugins may override
GROQ_REQUESTS_PER_MINUTE=30
GROQ_TOKENS_PER_MINUTE=60000
GROQ_WORKER_CONCURRENCY=2
GROQ_MAX_RETRIES=4
# NOTE: temperature is NOT set here — each plugin declares its own.

# --- Slack ---
SLACK_BOT_TOKEN=xoxb-...
SLACK_TARGET_TYPE=user               # "user" or "channel"
SLACK_TARGET_ID=U0XXXXXXX            # user ID for DM, channel ID for channel
SLACK_USERNAME=Jarvis
SLACK_ICON_EMOJI=:robot_face:

# --- Site24x7 ---
SITE24X7_ZOHO_REFRESH_TOKEN=...
SITE24X7_CLIENT_ID=...
SITE24X7_CLIENT_SECRET=...
SITE24X7_DATACENTER=us               # us, eu, in, au, cn, jp

# --- AWS SecurityHub ---
# Each AWS-backed plugin gets its own credential namespace. If you want to
# reuse the same IAM user, set the same values in both — that's your call.
SECURITYHUB_AWS_REGION=us-east-1
SECURITYHUB_AWS_ACCESS_KEY_ID=...
SECURITYHUB_AWS_SECRET_ACCESS_KEY=...
# or: SECURITYHUB_AWS_PROFILE=...   # if mounting ~/.aws
SECURITYHUB_MAX_FINDINGS=200

# --- AWS Billing (Cost Explorer) ---
BILLING_AWS_REGION=us-east-1
BILLING_AWS_ACCESS_KEY_ID=...
BILLING_AWS_SECRET_ACCESS_KEY=...
# or: BILLING_AWS_PROFILE=...
BILLING_CURRENCY=USD
BILLING_GROUP_BY=SERVICE              # SERVICE, LINKED_ACCOUNT, TAG, etc.
# Quarters are calendar-year only (Jan/Apr/Jul/Oct). Not configurable.
# Cost Explorer requires ce:GetCostAndUsage; enable CE in the AWS account.

# --- Drata ---
DRATA_API_KEY=...
DRATA_BASE_URL=https://public-api.drata.com

# --- Gmail ---
GMAIL_CLIENT_ID=...
GMAIL_CLIENT_SECRET=...
GMAIL_REFRESH_TOKEN=...
GMAIL_USER=graham.brooks@avatarfleet.com
GMAIL_QUERY=in:inbox newer_than:1d    # default: everything in the inbox from the last 24h

# --- GitHub ---
GITHUB_TOKEN=ghp_...                 # PAT with repo + read:org scopes (or fine-grained equivalent)
GITHUB_USER=GrahamBrooks             # whose activity to report on
GITHUB_ORGS=avatarfleet               # comma-separated; PRs across these orgs
GITHUB_REPOS=                        # optional comma-separated owner/repo overrides
GITHUB_STALE_PR_DAYS=14              # PR counted as "stale" if open with no update this long

# --- Weather ---
WEATHER_ZIP_CODE=43017               # required; home/office ZIP used for the forecast lookup
WEATHER_COUNTRY_CODE=US              # ISO 3166 country code; defaults to US
WEATHER_API_KEY=...                  # OpenWeatherMap API key (free tier is fine)
WEATHER_UNITS=imperial               # "imperial" (°F, mph) or "metric" (°C, m/s)

# --- News (multi-source RSS aggregator) ---
# Comma-separated list of RSS feed URLs. Plugin reads the <channel><title> from each
# feed to label its section. To add a source, append a URL. To remove one, delete it.
NEWS_FEEDS=https://feeds.bbci.co.uk/news/world/rss.xml,http://rss.cnn.com/rss/cnn_topstories.rss,https://moxie.foxnews.com/google-publisher/us.xml,https://feeds.npr.org/1001/rss.xml,https://www.theguardian.com/international/rss,https://apnews.com/index.rss
NEWS_ITEMS_PER_FEED=10               # cap per source so one outlet can't dominate the payload
NEWS_DEDUPE=true                     # collapse near-duplicate headlines across feeds

# --- Stocks ---
STOCKS_TICKERS=AAPL,MSFT,NVDA,GOOGL  # your watchlist; comma-separated symbols
STOCKS_INCLUDE_INDICES=true          # auto-include S&P 500, Nasdaq, Dow, VIX for market context
STOCKS_NEWS_PER_TICKER=3             # cap per-ticker headlines pulled from Yahoo Finance
STOCKS_PROVIDER=yfinance             # "yfinance" (no key) or "alpha_vantage" (requires key)
ALPHA_VANTAGE_API_KEY=               # only needed if STOCKS_PROVIDER=alpha_vantage

# --- Trump (Truth Social) ---
TRUMP_FEED_URL=https://www.trumpstruth.org/feed   # default: trumpstruth.org RSS archive
TRUMP_MAX_POSTS=50                   # cap posts pulled per run; Trump can post prolifically
```

### Plugin-local env convention

Each plugin's env vars are prefixed with the plugin name (uppercased). A plugin should never read env vars outside its own prefix or the shared `GROQ_*` / `SLACK_*` / `RUN_WINDOW_HOURS` space. This keeps plugins relocatable.

---

## 5. Plugin contract

Every plugin is a self-contained Python package in `plugins/<plugin_name>/` with this shape:

```
plugins/
  site24x7/
    __init__.py
    plugin.py          # implements DataSourcePlugin (fetch + summarize config)
    auth.py            # plugin-local authentication (see §5.2)
    prompt.md          # the LLM prompt used to summarize this source
    chunker.py         # optional: custom map-reduce splitter for this payload
    setup.py           # optional: one-time interactive setup (OAuth dance, etc.)
    fixtures/          # optional: recorded API responses for tests
    README.md          # human-facing notes: what creds, what it fetches
```

A plugin folder is the unit of portability. Everything the plugin needs to fetch, authenticate, shape its payload, and prompt the LLM lives inside its folder. The core never knows the shape of a plugin's payload or how it logged in.

### 5.1 Interface

```python
# jarvis/core/plugin.py
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Optional

@dataclass
class FetchResult:
    source_name: str             # "Site24x7", "AWS SecurityHub", etc.
    raw_payload: Any             # JSON-serializable; schema is defined by the plugin
    metadata: dict = field(default_factory=dict)  # counts, window, api version, etc.
    links: list[str] = field(default_factory=list)  # optional URLs for Slack "See more"

class DataSourcePlugin(ABC):

    # --- Identity ---
    name: str                    # short id, matches ENABLED_PLUGINS entry
    display_name: str            # human-readable, used in the digest header

    # --- Environment ---
    required_env_vars: list[str] # loader validates presence up front

    # --- Inference parameters (plugin-owned) ---
    temperature: float = 0.2     # e.g. 0.1 for Billing, 0.3 for Gmail tone paraphrasing
    max_tokens: int = 800        # cap on the summary output
    model_override: Optional[str] = None  # if set, overrides GROQ_MODEL for this plugin

    @abstractmethod
    async def fetch(self, window_hours: int) -> FetchResult:
        """Pull the last `window_hours` of activity. Must be idempotent.
        The schema of FetchResult.raw_payload is entirely up to the plugin.
        """
        ...

    def prompt_template(self) -> str:
        """Return the prompt template. Default loads prompt.md next to plugin.py."""
        ...

    def chunker(self):
        """Return a callable that splits an oversized payload into chunks.
        Default: split on top-level JSON array elements. Override in chunker.py
        if the plugin's payload shape demands it (e.g. a dict-of-lists like Billing).
        """
        ...

    def redact(self, payload: Any) -> Any:
        """Scrub sensitive fields from the payload BEFORE it leaves the container
        for Groq. Must return a payload of the same shape the prompt expects.
        Default is identity (no redaction). Override in the plugin when the raw
        payload contains values the operator doesn't want sent to a third-party
        inference provider.
        """
        return payload
```

### 5.2 Plugin-local authentication

Authentication is owned by the plugin, not the core. Each plugin folder contains an `auth.py` module that exposes a single `get_authenticated_client()` (or equivalent) callable. The core never imports a credential library directly.

This is important because data sources span very different auth patterns, and we want the framework to accommodate all of them without special-casing:

- API key header (Drata, Groq, Site24x7 once exchanged)
- OAuth2 refresh-token flow (Gmail, Site24x7 initial exchange)
- AWS SigV4 via boto3 sessions built from plugin-namespaced env vars (each AWS-backed plugin defines its own `<PLUGIN>_AWS_*` credentials; SecurityHub and Billing are separate)
- Future: mTLS, AWS STS assume-role, Azure service principal, GCP service account, HMAC-signed requests, etc.

To keep the plugin authors' lives easy, a small set of optional **auth helpers** ships with the core in `jarvis/core/auth/`:

```
jarvis/core/auth/
  __init__.py
  api_key.py         # header-based bearer / X-API-Key helpers
  oauth2.py          # authorization-code + refresh-token flow
  aws.py             # boto3 session builder honoring profile / static creds
```

Plugins may use these helpers, wrap them, or ignore them and implement auth from scratch. The only contract is:

```python
# plugins/<name>/auth.py
async def get_authenticated_client():
    """Return a fully-authenticated client object the plugin will use in fetch().
    Any shape is acceptable — a boto3 client, an httpx.AsyncClient with headers,
    a Google API resource, whatever this source needs.
    """
```

If a plugin requires a one-time human-in-the-loop auth step (e.g. Gmail's OAuth consent screen), it ships a `setup.py` in its own folder that the operator runs once locally to populate the necessary env vars. The core is never involved in this step.

### 5.3 Plugin-owned redaction

Each plugin decides what (if anything) to strip from its raw payload before the summarizer hands it to Groq. This lives on the plugin — not on the core — because the core has no model of which fields in a plugin-defined payload are sensitive.

The contract is a single method on `DataSourcePlugin`:

```python
def redact(self, payload: Any) -> Any: ...
```

The summarizer calls `plugin.redact(payload)` immediately after `fetch()` and before any token counting, chunking, or queueing. Everything downstream sees the redacted payload only. The original payload is never persisted or logged.

Plugin-specific redaction examples to implement in v1:

- **Gmail:** strip full email bodies down to a snippet (already described in §6.5). Optionally mask `to:` addresses that aren't on an allow-list, or hash external recipient addresses.
- **SecurityHub:** drop `AwsAccountId` if the operator doesn't want account numbers in transit; collapse `Resources[].Id` ARNs to their resource type.
- **GitHub:** nothing to redact by default — PR titles and URLs are public within the org.
- **AWS Billing:** no redaction by default (numbers are the payload).
- **Drata:** strip personnel email addresses and replace with opaque user IDs if desired.
- **Site24x7:** strip internal monitor URLs if they contain ticketing hostnames.

Shared helpers (regex-based masking for obvious secrets — AWS keys, JWTs, bearer tokens — that might leak into any payload) live in `jarvis/core/redaction.py` and can be imported and composed by any plugin that wants them. But invocation is up to the plugin. The core never redacts on a plugin's behalf.

### 5.4 Prompt template convention

Each `prompt.md` is a Jinja2-style template rendered with:

- `{{ payload }}` — JSON-stringified raw payload (or chunk, in map-reduce)
- `{{ metadata }}` — metadata dict
- `{{ window_hours }}`
- `{{ today }}`

The template must instruct Groq to produce markdown in the §3.4 output contract.

---

## 6. Initial plugins (v1)

Each plugin ships with its own `plugin.py`, `auth.py`, `prompt.md`, and `README.md`. The list below summarizes what each pulls, how it authenticates, what prompt angle it takes, and any payload-shaping notes.

### 6.1 Site24x7

**What it pulls:**
- Alerts / incidents from the last 24h (`/api/alert_logs`)
- Current down monitors (`/api/current_status` filtered to DOWN/TROUBLE)
- SLA breaches if any

**Auth:** Zoho OAuth2 refresh-token flow. Plugin exchanges refresh token → access token at the start of each run.

**Prompt focus:** "What broke overnight, what's still down, which services are at risk of SLA breach."

### 6.2 AWS SecurityHub

**What it pulls:**
- `get_findings` filtered to `UpdatedAt >= now-24h`, `RecordState = ACTIVE`, `WorkflowStatus != SUPPRESSED|RESOLVED`
- Aggregated counts by severity and by standard (CIS, PCI, FSBP)

**Auth:** `plugins/securityhub/auth.py` builds a boto3 session from its own namespaced env vars (`SECURITYHUB_AWS_ACCESS_KEY_ID`, `SECURITYHUB_AWS_SECRET_ACCESS_KEY`, `SECURITYHUB_AWS_REGION`, or `SECURITYHUB_AWS_PROFILE`). IAM policy: `securityhub:GetFindings`, `securityhub:DescribeHub`.

**Payload handling:** SecurityHub responses can be huge. Plugin should:
- Request only needed fields via `Filters`
- Cap at e.g. 200 findings per run (configurable via `SECURITYHUB_MAX_FINDINGS`)
- Rely on the summarizer's map-reduce if still too large

**Prompt focus:** "Critical/high findings introduced in the last 24h, anything touching IAM or public-facing resources, which account(s), one-line remediation pointer if obvious."

### 6.3 AWS Billing (Cost Explorer)

**What it pulls:** three parallel Cost Explorer queries, reduced into a single payload:

- **Today:** `GetCostAndUsage` with `Granularity=DAILY`, `TimePeriod` covering the current calendar day (UTC). Grouped by `BILLING_GROUP_BY` (default `SERVICE`).
- **Month-to-date:** `Granularity=MONTHLY`, `TimePeriod` from the 1st of the current month through today. Includes the same-period prior month for comparison so the prompt can reason about pacing.
- **Quarter-to-date:** anchored to the calendar year (Q1 = Jan–Mar, Q2 = Apr–Jun, Q3 = Jul–Sep, Q4 = Oct–Dec). Monthly granularity across the quarter with per-service totals and a quarter-over-quarter comparison to the previous quarter's same elapsed-days window. No fiscal-year override.

**Auth:** `plugins/aws_billing/auth.py` builds its own boto3 session from namespaced env vars (`BILLING_AWS_*`). These are deliberately separate from SecurityHub's — you can point Billing at a consolidated payer account while SecurityHub stays on a workload account, or reuse the same credentials by setting the same values in both. IAM policy: `ce:GetCostAndUsage`, `ce:GetCostForecast` (forecast is optional but useful for "on track for $X this month"). Cost Explorer must be enabled in the account; first-run errors should surface clearly.

**Payload shape (plugin-defined):**

```json
{
  "today":     { "total": 142.37, "by_service": [...], "date": "2026-04-23" },
  "mtd":       { "total": 2841.02, "by_service": [...], "prior_mtd": 2614.88, "pct_delta": 8.7 },
  "qtd":       { "total": 8921.45, "by_service": [...], "prior_qtd_sameperiod": 8102.11, "pct_delta": 10.1 },
  "forecast":  { "month_end": 4120.00, "quarter_end": 12400.00 }
}
```

**Prompt focus:** "How much was spent today, is the month-to-date pacing above/below the prior month, is the quarter on track, top 3 services driving the bill, any unusual spike vs. yesterday." Temperature: very low (e.g. 0.1) — the summary must be numerically faithful.

**Notes:** Cost Explorer data lags by up to 24 hours, and AWS bills it per API call ($0.01 each as of last check) — keep the number of queries small. The plugin should cache nothing; the run is ephemeral.

### 6.4 Drata

**What it pulls:**
- Failing controls (`/v1/controls?status=FAILING`)
- Personnel compliance tasks overdue or due-soon
- New evidence requests
- Audit-relevant changes in the last 24h

**Auth:** Drata public API key, Bearer auth.

**Prompt focus:** "Controls that started failing, who has overdue compliance tasks, upcoming audit deadlines within 7 days."

### 6.5 Gmail

**What it pulls:**
- Every message in the Inbox from the last 24 hours. The default `GMAIL_QUERY` is `in:inbox newer_than:1d` — no category filtering, no sender filtering. If a message landed in the inbox, it goes to the LLM.
- For each message: subject, from, to, snippet, date, is_unread, has_attachments, labels, thread ID.
- The operator can override `GMAIL_QUERY` to narrow the scope, but the shipped default is "everything in the inbox."

**Auth:** Gmail API OAuth2 with a refresh token. `plugins/gmail/auth.py` exchanges refresh → access each run. One-time human consent is handled by `plugins/gmail/setup.py`, which the operator runs locally once to populate the `GMAIL_REFRESH_TOKEN` env var.

**Payload handling:** Body text is truncated per thread (e.g. 2KB) before being sent to Groq. Full bodies are not needed for a brief.

**Prompt focus:** "Summarize every message that hit the inbox in the last 24 hours. Group by theme or thread where it helps readability. Call out anything that appears to need a response, anything time-sensitive, and anything that looks automated vs. human. No sender allow-list — every message gets equal consideration; it's up to the prompt to surface what matters."

### 6.6 GitHub

**What it pulls:** a single payload covering PR activity and Graham's own code volume over the last 24 hours.

- **New PRs:** opened in the window across `GITHUB_ORGS` (optionally restricted to `GITHUB_REPOS`). Captures: number, title, repo, author, draft flag, reviewers, URL.
- **Closed PRs:** closed or merged in the window. Captures the same plus `merged_at` vs `closed_at` so the prompt can distinguish merged-vs-abandoned.
- **Stale PRs:** still open with no update in the last `GITHUB_STALE_PR_DAYS` days (default 14). This is the biggest signal for "something Graham should nudge."
- **Graham's code volume (previous day):** aggregate lines added and lines deleted across all commits authored by `GITHUB_USER` on the previous calendar day (UTC). Computed entirely via GraphQL (see below). Also includes: number of commits, number of distinct repos touched.

**Payload shape (plugin-defined):**

```json
{
  "window_hours": 24,
  "user": "GrahamBrooks",
  "prs": {
    "new":    [ { "repo": "...", "number": 42, "title": "...", "author": "...", "url": "...", "draft": false, "reviewers": ["..."] } ],
    "closed": [ { "repo": "...", "number": 39, "merged": true,  "merged_by": "...", "url": "..." } ],
    "stale":  [ { "repo": "...", "number": 27, "days_since_update": 23, "title": "...", "url": "..." } ]
  },
  "code_volume_yesterday": {
    "date": "2026-04-22",
    "commits": 11,
    "repos_touched": ["avatarfleet/jarvis-executive-summary", "avatarfleet/api-core"],
    "additions": 412,
    "deletions": 178,
    "net": 234
  }
}
```

**Auth:** `plugins/github/auth.py` builds an authenticated `httpx.AsyncClient` against `https://api.github.com/graphql` using a PAT from `GITHUB_TOKEN`. Fine-grained tokens are preferred. The token needs: `repo` (read), `read:org` (to enumerate org-scoped PRs), and no write scopes.

**Payload handling — GraphQL-only.** The plugin exclusively uses the GitHub GraphQL API. No REST. This matters because commit-level additions/deletions are available as first-class fields on GraphQL `Commit` nodes, which eliminates the N+1 REST call pattern (where you'd otherwise hit `/repos/{o}/{r}/commits/{sha}` once per commit to get stats).

Two queries per run, in this order:

**Query 1 — PR buckets (all three in one round-trip using GraphQL `search`):**

```graphql
query PRs($newQ: String!, $closedQ: String!, $staleQ: String!) {
  new:    search(query: $newQ,    type: ISSUE, first: 50) { nodes { ... on PullRequest { number title url author { login } repository { nameWithOwner } isDraft reviewRequests(first: 10) { nodes { requestedReviewer { ... on User { login } } } } } } }
  closed: search(query: $closedQ, type: ISSUE, first: 50) { nodes { ... on PullRequest { number title url repository { nameWithOwner } merged mergedAt closedAt mergedBy { login } } } }
  stale:  search(query: $staleQ,  type: ISSUE, first: 50) { nodes { ... on PullRequest { number title url repository { nameWithOwner } updatedAt } } }
}
```

Search strings are built with `is:pr`, `org:<ORG>`, and date-range qualifiers (`created:>=…`, `closed:>=…`, `is:open updated:<=…`).

**Query 2 — code volume (one query, aliased per repo the user touched yesterday):**

Step A: one call to `viewer.contributionsCollection(from, to).commitContributionsByRepository` to discover which repos saw commits from `GITHUB_USER` yesterday.

Step B: a single GraphQL request with one aliased sub-query per repo, pulling commit history with additions/deletions:

```graphql
query CodeVolume($since: GitTimestamp!, $until: GitTimestamp!, $author: ID!) {
  r0: repository(owner: "avatarfleet", name: "jarvis-executive-summary") {
    defaultBranchRef { target { ... on Commit {
      history(since: $since, until: $until, author: { id: $author }) {
        nodes { additions deletions committedDate }
      }
    } } }
  }
  r1: repository(owner: "avatarfleet", name: "api-core") { ... }
  # ... one alias per repo from step A
}
```

The plugin sums `additions` and `deletions` across all returned commits, counts distinct repos, and produces the `code_volume_yesterday` block. Total GitHub API cost per Jarvis run: 3 GraphQL requests (PR buckets + contributions discovery + aliased history batch), regardless of commit count.

PR lists still cap at 50 per category to protect prompt size. Commit stats never reach the LLM — only the aggregate totals do.

**Prompt focus:** "How many PRs opened/closed/stalled overnight, which stale PRs have been sitting the longest, how much code Graham shipped yesterday framed as a one-liner (e.g. '11 commits across 2 repos, +412/-178'). Don't editorialize code volume — just report it." Temperature: 0.2.

### 6.7 Weather

**Why it's in the brief:** it's a morning digest. The user wants to know if they need a jacket before they leave the house. Not operational, not security — just useful life context alongside the rest of the morning context.

**What it pulls:** today's conditions and outlook for the ZIP code in `WEATHER_ZIP_CODE`. Two calls to OpenWeatherMap's free tier:

- `GET /data/2.5/weather?zip={zip},{country}&units={units}&appid={key}` — current conditions
- `GET /data/2.5/forecast?zip={zip},{country}&units={units}&appid={key}` — 5-day / 3-hour forecast; plugin reduces this to "today" and "tomorrow" buckets with hi/lo, precip chance, and a short descriptor

**Payload shape (plugin-defined):**

```json
{
  "location":  { "zip": "43017", "city": "Dublin", "country": "US" },
  "units":     { "temp": "F", "wind": "mph" },
  "now":       { "temp": 58, "feels_like": 54, "conditions": "Light rain", "wind": 12, "humidity": 81 },
  "today":     { "high": 64, "low": 46, "precip_chance": 0.75, "summary": "Showers clearing by evening" },
  "tomorrow":  { "high": 71, "low": 52, "precip_chance": 0.10, "summary": "Mostly sunny" }
}
```

**Auth:** `plugins/weather/auth.py` builds an `httpx.AsyncClient` with `WEATHER_API_KEY` appended to each request. No OAuth, no refresh tokens.

**Payload handling:** tiny — a couple hundred bytes after reduction. No chunking ever needed. Token budget for the summary is small (`max_tokens: 150`).

**Prompt focus:** "One-sentence current conditions, one-sentence day outlook, one-sentence tomorrow teaser. Keep it short. If there's something actionable (heavy rain, heat warning, freeze), lead with it." Temperature: 0.3.

**Provider swap:** OpenWeatherMap is the default because its free tier accepts ZIP directly. A plugin author can swap to another provider (NOAA / api.weather.gov, WeatherAPI, Open-Meteo) by rewriting `plugin.py` and `auth.py` — the payload contract stays the same.

### 6.8 News (multi-source RSS)

**What it is:** a source-agnostic news aggregator. The plugin reads a list of RSS feed URLs from `NEWS_FEEDS` in `.env`, fetches all of them in parallel, and produces a single unified payload. Adding or removing a news source is just editing the env var — no code change.

**Why RSS, not a news API:** every major news API worth using either requires a paid tier, gates content behind keys that expire, or couples you to a single outlet. Meanwhile, essentially every major newsroom still publishes free, keyless, unrate-limited RSS 2.0 feeds that have been stable for 15+ years. RSS is boring, ubiquitous, and perfect for this use case.

**Default source list** (shipped in `.env.example`):

| Outlet         | Feed URL                                                  | Notes                          |
|----------------|-----------------------------------------------------------|--------------------------------|
| BBC World      | `https://feeds.bbci.co.uk/news/world/rss.xml`             | International, UK-based        |
| CNN            | `http://rss.cnn.com/rss/cnn_topstories.rss`               | US, center-left editorial      |
| Fox News US    | `https://moxie.foxnews.com/google-publisher/us.xml`       | US, right-leaning editorial    |
| NPR            | `https://feeds.npr.org/1001/rss.xml`                      | US, public-media               |
| The Guardian   | `https://www.theguardian.com/international/rss`           | International, UK-based, left-leaning |
| AP News        | `https://apnews.com/index.rss`                            | US, wire service, center       |

Deliberately balanced across political orientation and geography so the morning brief doesn't reflect a single outlet's worldview. Operator can add, remove, or reweight by editing `NEWS_FEEDS`. Reuters is notable by its absence — Reuters removed its public RSS feeds in 2020 and no free replacement exists.

**Fetching:** all feeds are fetched concurrently via `httpx.AsyncClient` + `feedparser`. Each feed contributes up to `NEWS_ITEMS_PER_FEED` (default 10) of its newest items published within the run window. A per-feed timeout (10s) keeps a single slow outlet from blocking the run.

**Dedupe:** when `NEWS_DEDUPE=true`, the plugin collapses near-duplicate headlines across feeds using simple normalized-title similarity (lowercase, strip punctuation, Jaccard over token sets ≥ 0.6). Duplicates aren't dropped — they're merged into a single item that carries a list of sources. This matters because **a story covered by 4 outlets is a strong signal of significance**, and the prompt uses that signal.

**Auth:** none. `plugins/news/auth.py` returns an `httpx.AsyncClient` with a descriptive User-Agent. No keys, no tokens, no login.

**Payload shape (plugin-defined):**

```json
{
  "window_hours": 24,
  "feed_count":   6,
  "items": [
    {
      "title":     "Fed holds rates steady, signals two cuts in 2026",
      "summary":   "Short description lifted from the RSS <description> field, HTML stripped.",
      "published": "2026-04-23T10:15:00Z",
      "sources":   [
        { "outlet": "BBC News",    "url": "https://www.bbc.co.uk/news/..." },
        { "outlet": "AP News",     "url": "https://apnews.com/..." },
        { "outlet": "The Guardian", "url": "https://www.theguardian.com/..." }
      ],
      "source_count": 3
    }
  ]
}
```

Items are sorted by `source_count` descending, then by recency. The prompt therefore sees the most widely-covered stories first.

**Payload handling:** the full payload is usually in the 3–8k token range — well within context. No chunking needed. If a user adds enough feeds to exceed the window, the default JSON-array chunker kicks in.

**Prompt focus:** "Summarize the morning's news. Lead with the 3 stories with the highest `source_count` (widely-reported = significant). Produce 6–10 bullets total. For each bullet, include the story and the outlets covering it (e.g. 'Fed holds rates — per BBC, AP, Guardian'). Do not editorialize, characterize outlets as biased, or add commentary beyond what's in the summaries. Under **Attention**, flag anything market-moving, geopolitically escalating, or affecting US operations." Temperature: 0.2.

**Extensibility notes:** the plugin doesn't care whether a feed is RSS 2.0, RSS 1.0, or Atom — `feedparser` handles all three. That means pointing `NEWS_FEEDS` at a niche blog, an industry trade publication, a SEC filings feed, or a GitHub release feed all Just Work. This plugin can quietly become an "anything-syndicated" aggregator.

### 6.9 Stocks

**Division of responsibility:** the `news` plugin already handles arbitrary RSS feeds — if you want MarketWatch or CNBC market-news headlines in the brief, just append their RSS URLs to `NEWS_FEEDS`. This plugin does the thing the news plugin can't: **actual price and volume data with trend indicators on a personal watchlist**, plus ticker-scoped news aggregated by Yahoo Finance's own news system.

**What it pulls** (per ticker in `STOCKS_TICKERS`):

- Latest price and previous close
- Percent change: day, week, month, YTD
- 52-week high, low, and position (0.0–1.0, where the current price sits in that range)
- Yesterday's volume and 30-day average volume (plus a `volume_ratio` for unusual-activity detection)
- Up to `STOCKS_NEWS_PER_TICKER` headlines from Yahoo Finance's per-ticker news feed

**Market context** (if `STOCKS_INCLUDE_INDICES=true`, which is the default):

- `^GSPC` (S&P 500), `^DJI` (Dow Jones), `^IXIC` (Nasdaq), `^VIX` (volatility index)
- Same fields as tickers but no news — these are context, not the focus.

**Auth:** none when using the default `yfinance` provider. The `yfinance` Python library reads Yahoo Finance's unofficial endpoints without any key, token, or registration. `plugins/stocks/auth.py` is effectively a no-op — it can return a configured `httpx.AsyncClient` if the plugin needs one for future providers, otherwise `None`.

**Payload shape (plugin-defined):**

```json
{
  "as_of":         "2026-04-23T06:00:00Z",
  "market_state":  "closed|pre-market|open|post-market",
  "currency":      "USD",
  "indices": [
    { "symbol": "^GSPC", "name": "S&P 500",  "last": 5821.45, "previous_close": 5841.10,
      "change_pct_day": -0.34, "change_pct_week": -0.8, "change_pct_month": 2.1,
      "change_pct_ytd": 6.4, "52w_high": 5940.22, "52w_low": 4810.00, "52w_position": 0.89 }
  ],
  "tickers": [
    {
      "symbol":          "NVDA",
      "name":            "NVIDIA Corporation",
      "last":            875.23,
      "previous_close":  862.10,
      "change_pct_day":  1.52,
      "change_pct_week": 3.21,
      "change_pct_month": 8.45,
      "change_pct_ytd":  45.23,
      "52w_high":        974.00,
      "52w_low":         412.00,
      "52w_position":    0.80,
      "volume":          48234123,
      "avg_volume_30d":  41000000,
      "volume_ratio":    1.18,
      "news": [
        { "title": "...", "publisher": "Reuters", "published": "2026-04-22T18:23:00Z", "url": "..." }
      ]
    }
  ]
}
```

**Payload handling:** payload size scales linearly with ticker count. 5–10 tickers plus indices stays under 5k tokens — no chunking needed. A watchlist of 50+ tickers would warrant `NEWS_PER_TICKER=1` or disabling news entirely.

**Prompt focus:** "Lead with a one-line market pulse drawn from the indices — what direction the market moved yesterday and what the VIX is saying about volatility. Then summarize the watchlist: call out any ticker with day change > 3% in either direction, any ticker at or near its 52-week high/low (position > 0.95 or < 0.05), and any ticker with `volume_ratio` > 1.5 (unusual activity — often news-driven). Cluster themes across news items when tickers move in tandem. Do not give buy/sell recommendations, price predictions, or analyst ratings — just describe what the market did." Temperature: 0.2.

**Provider swap:** the default `yfinance` path is free but fragile — Yahoo occasionally changes its site structure and yfinance breaks until a new release lands. If reliability matters more than zero-cost, set `STOCKS_PROVIDER=alpha_vantage` and populate `ALPHA_VANTAGE_API_KEY`. Alpha Vantage's free tier is capped at 25 requests/day, which is enough for a daily-run Jarvis with ~20 tickers. The plugin's `fetch()` dispatches on `STOCKS_PROVIDER` and both paths produce the same payload shape.

**Reliability notes:** yfinance pulls data via scraping Yahoo Finance's JSON endpoints, which are technically unofficial. In practice this has been stable for years but can break suddenly. When it breaks, the plugin degrades gracefully (section shows "market data unavailable" and the rest of the brief proceeds). If yfinance has been broken for more than a day or two, check for a library update before assuming Yahoo has killed the endpoints for good.

**Data timing caveats:**

- Data is delayed 15–20 minutes during market hours (Yahoo's standard delay for unauthenticated access).
- If Jarvis runs pre-market, "yesterday's close" is the most recent data point; intraday moves won't exist yet.
- Market state is surfaced in the payload so the prompt can phrase correctly ("markets open in 3 hours" vs "markets closed up 0.4% yesterday").

### 6.10 Trump (Truth Social)

**What it pulls:** posts from `@realDonaldTrump` on Truth Social in the last `RUN_WINDOW_HOURS`. Trump migrated to Truth Social after his 2021 Twitter suspension and, although he was reinstated on X in late 2022, Truth Social remains where nearly all of his output goes. The plugin name is `trump` for brevity; calling it `tweets` would be technically wrong.

**Source — primary:** the RSS feed at `https://www.trumpstruth.org/feed`, served by an independent archive site (not affiliated with Truth Social or the Trump campaign). The feed:

- Is free, requires no API key, and has no authentication.
- Supports date-range filtering via `?start_date=YYYY-MM-DD&end_date=YYYY-MM-DD` query parameters — the plugin uses these to scope to the run window rather than pulling and client-side filtering.
- Returns standard RSS 2.0 XML with one `<item>` per post. Each item contains `title`, `description` (the post text, HTML-escaped), `pubDate`, `link` (back to trumpstruth.org), and `guid`.

**Source — fallback:** if trumpstruth.org is unreachable, the plugin can be pointed at the `stiles/trump-truth-social-archive` GitHub raw JSON file (updated every few minutes) by setting `TRUMP_FEED_URL` to its raw.githubusercontent.com URL. The plugin detects `.xml`/`.rss` vs `.json` via URL suffix and parses accordingly.

**Auth:** none. `plugins/trump/auth.py` just returns an `httpx.AsyncClient` with a reasonable User-Agent string — no headers, no tokens.

**Payload shape (plugin-defined):**

```json
{
  "source":       "trumpstruth.org",
  "window_hours": 24,
  "post_count":   14,
  "posts": [
    {
      "id":         "113xxxxxxxxxxxxx",
      "published":  "2026-04-22T23:41:00Z",
      "text":       "Post content with HTML decoded, @mentions and #hashtags preserved.",
      "url":        "https://www.trumpstruth.org/statuses/...",
      "is_reply":   false,
      "is_repost":  false,
      "media_count": 0
    }
  ]
}
```

**Payload handling:** cap at `TRUMP_MAX_POSTS` (default 50) newest posts within the window to protect prompt size — posting volume is bursty and a single overnight spree can run into triple digits. HTML tags in the description are stripped to plain text before forwarding. URLs inside the text are preserved but not expanded.

**Prompt focus:** "Count and summarize. Report how many posts were made, then produce 3–5 neutral bullet points grouping posts by topic. Quote the post verbatim when a bullet calls out a specific claim. Do not editorialize, fact-check, or characterize tone — just report what was said and let the reader form their own view. If any post references breaking news, foreign policy, or market-moving statements, flag it under **Attention**." Temperature: 0.2.

**Political sensitivity:** this source is unlike the others — it's opinion content from a political figure. The prompt is deliberately written to be descriptive rather than interpretive, and the plugin does not enrich posts with external context. If this plugin is a net negative on the morning brief's usefulness, disable it by removing `trump` from `ENABLED_PLUGINS`.

**Reliability notes:** trumpstruth.org is a volunteer-maintained third-party site with no SLA. The plugin treats a feed fetch failure like any other plugin failure: the digest section shows "unavailable" and the rest of the brief goes out. If long-term reliability matters, the operator should point `TRUMP_FEED_URL` at the stiles GitHub archive, which is similarly free but backed by versioned git storage.

---

## 7. Directory layout

```
jarvis-executive-summary/
├── Dockerfile
├── docker-compose.yml            # example for local runs
├── pyproject.toml                # poetry or uv
├── .env.example                  # template, no real secrets
├── README.md
├── SPEC.md                       # this document
├── jarvis/
│   ├── __init__.py
│   ├── __main__.py               # container entrypoint (runs once and exits)
│   ├── config.py                 # loads .env, validates
│   ├── orchestrator.py           # run-once pipeline
│   └── core/
│       ├── plugin.py             # DataSourcePlugin ABC + FetchResult
│       ├── loader.py             # plugin discovery
│       ├── groq_queue.py         # async queue + rate limiter
│       ├── summarizer.py         # prompt rendering, map-reduce, LLM call
│       ├── slack.py              # Block Kit assembly + post (user DM or channel)
│       ├── logging.py
│       ├── redaction.py          # optional regex helpers plugins can compose (keys, JWTs, bearer tokens)
│       └── auth/                 # optional helpers plugins can compose with
│           ├── api_key.py
│           ├── oauth2.py
│           └── aws.py
├── plugins/                      # each plugin is a self-contained folder
│   ├── __init__.py
│   ├── site24x7/
│   │   ├── __init__.py
│   │   ├── plugin.py
│   │   ├── auth.py               # Zoho OAuth2 refresh-token exchange
│   │   ├── prompt.md
│   │   └── README.md
│   ├── securityhub/
│   │   ├── plugin.py
│   │   ├── auth.py               # boto3 session builder
│   │   ├── prompt.md
│   │   └── README.md
│   ├── aws_billing/
│   │   ├── plugin.py
│   │   ├── auth.py               # boto3 session from BILLING_AWS_* env vars
│   │   ├── chunker.py            # dict-of-lists chunker (today/mtd/qtd)
│   │   ├── prompt.md
│   │   └── README.md
│   ├── drata/
│   │   ├── plugin.py
│   │   ├── auth.py               # API-key bearer
│   │   ├── prompt.md
│   │   └── README.md
│   ├── gmail/
│   │   ├── plugin.py
│   │   ├── auth.py               # OAuth2 refresh -> access at runtime
│   │   ├── setup.py              # one-time local consent flow
│   │   ├── prompt.md
│   │   └── README.md
│   ├── github/
│   │   ├── plugin.py
│   │   ├── auth.py               # PAT-based httpx client
│   │   ├── prompt.md
│   │   └── README.md
│   ├── weather/
│   │   ├── plugin.py
│   │   ├── auth.py               # httpx client with API key
│   │   ├── prompt.md
│   │   └── README.md
│   ├── news/
│   │   ├── plugin.py             # parallel RSS fetch + feedparser + dedupe
│   │   ├── auth.py               # no-op (public feeds); UA-tagged httpx client
│   │   ├── prompt.md
│   │   └── README.md
│   ├── stocks/
│   │   ├── plugin.py             # yfinance by default; alpha_vantage fallback
│   │   ├── auth.py               # no-op for yfinance; API-key path for alpha_vantage
│   │   ├── prompt.md
│   │   └── README.md
│   └── trump/
│       ├── plugin.py             # fetches + parses RSS or JSON from TRUMP_FEED_URL
│       ├── auth.py               # no-op (public feed); returns a UA-tagged httpx client
│       ├── prompt.md
│       └── README.md
├── scripts/
│   └── dry_run.py                # run locally, print digest to stdout instead of Slack
└── tests/
    ├── test_loader.py
    ├── test_groq_queue.py
    ├── test_summarizer_chunking.py
    └── plugins/
        └── test_plugin_contract.py
```

Note: the `plugins/` directory sits at the repo root, not under `jarvis/`. This is intentional — it emphasizes that plugins are first-class extension points rather than internal modules, and lets operators fork/vendor plugins without touching core code.

---

## 8. Containerization

**Base image:** `python:3.12-slim`

**Dockerfile responsibilities:**
- Install dependencies (poetry or uv)
- Copy `jarvis/` source and `plugins/`
- `CMD ["python", "-m", "jarvis"]`
- No baked-in secrets; `.env` is mounted at runtime (read-only)

**Execution model:**
The container performs one run and exits. There is no internal scheduler, no loop, no idle state, no "daemon" mode. The lifecycle is literally: start → load plugins → fetch all → summarize all → post to Slack → exit 0 (or non-zero on fatal error).

How the container is invoked is entirely the operator's concern and is **not** addressed by this project. We are not shipping any infrastructure-as-code, Terraform, CloudFormation, EventBridge, CronJob manifests, or systemd units. The v1 deliverables are:

- `Dockerfile`
- `docker-compose.yml` — a convenience file for local runs (`docker compose run --rm jarvis`)

Anything beyond that — putting the container on a host, scheduling it, wiring it to EventBridge, etc. — is out of scope for this codebase.

**Dry-run mode:** `JARVIS_DRY_RUN=true` skips Slack posting and prints the rendered Block Kit JSON to stdout — useful for prompt iteration without spamming Slack.

---

## 9. Observability

- Structured JSON logs to stdout (capture with host-level log collector).
- Each run logs: start time, per-plugin fetch duration, per-plugin token count submitted, Groq total tokens used, Slack post latency, total run duration.
- No metrics backend in v1. If needed later, add an OTLP exporter — kept out of scope.

---

## 10. Error handling & resilience

| Failure mode                        | Behavior                                                    |
| ----------------------------------- | ----------------------------------------------------------- |
| Plugin fetch times out              | Skip plugin, note in digest context block                   |
| Plugin raises unexpected exception  | Caught, logged with traceback, plugin marked failed         |
| Groq rate-limit (429)               | Exponential backoff with jitter, up to `GROQ_MAX_RETRIES`   |
| Groq hard failure after retries     | Plugin section shows fetch metadata + "summary unavailable" |
| Payload exceeds context window      | Map-reduce chunking in summarizer                           |
| Slack post fails                    | Log full digest to stdout as fallback                       |
| Missing env vars at startup         | Hard-fail with clear message; don't partial-run             |

---

## 11. Security considerations

- `.env` is the only secret surface. Container image contains no secrets.
- Recommend mounting `.env` read-only (`-v .env:/app/.env:ro`).
- All plugin HTTP clients use explicit TLS verification.
- Plugin-returned payloads may contain sensitive data (emails, findings, account IDs) and are transmitted to Groq for summarization. **Redaction is the plugin's responsibility**, not the core's. The core has no idea what's sensitive in a given payload — only the plugin author does. See §5.4 for the redaction hook on the plugin contract.
- Slack bot token scopes: `chat:write` for all posting, plus `im:write` and `users:read` when `SLACK_TARGET_TYPE=user` so `conversations.open` can resolve a DM. No write-capable scopes beyond these.

---

## 12. Testing strategy

- **Plugin contract test:** every plugin is instantiated with mock env vars and must satisfy the `DataSourcePlugin` interface and declare valid metadata. Runs in CI.
- **Queue tests:** rate-limiter math, backoff, worker concurrency, shutdown semantics.
- **Chunking tests:** map-reduce produces outputs that fit the context window and don't drop records.
- **Plugin integration tests:** each plugin has a `fixtures/` directory with a recorded API response, and a test that runs the full fetch→summarize→format pipeline against the fixture with a mocked Groq client.
- **Dry-run smoke test:** `scripts/dry_run.py` runs the full pipeline end-to-end against live APIs (local dev only) and prints the digest.

---

## 13. Future extensions (out of scope for v1)

- **Slash command:** `/jarvis brief` triggers an on-demand run.
- **Per-source cadence:** some sources hourly, others daily.
- **Historical store:** persist digests to pull trends ("SecurityHub findings up 30% week-over-week").
- **Additional plugins:** PagerDuty, Jira, Calendar, CloudTrail, Linear, Stripe — all drop-in.
- **User allow-lists and mute rules** configured in `.env` per plugin.
- **Thread drill-downs:** clicking a section expands details in a Slack thread.

---

## 14. Open questions

_None at this time — all previously-open questions have been resolved during spec review._
