# Jarvis — Executive Summary Agent

A containerized Python tool that pulls the last 24 hours of activity from a configurable set of data sources, summarizes each through Groq-hosted LLM inference, and posts a single consolidated executive brief to Slack — then exits.

One container, one run, one well-formatted morning digest. No daemon, no scheduler, no loop.

## What it does

On startup, Jarvis:

1. Reads `.env` and discovers which plugins to run from `ENABLED_PLUGINS`.
2. Runs every enabled plugin concurrently — each plugin fetches its own data and shapes its own payload.
3. Pipes each payload through Groq via an in-process, rate-limited queue, using the plugin's own prompt, temperature, and (optionally) model override.
4. Assembles the per-plugin summaries into a single Slack Block Kit message.
5. Posts it to a user DM or channel (configurable) and exits.

If a plugin fails, the digest still goes out with a note about the failed source — a partial brief beats silence.

## Initial data sources

Ten plugins ship with v1:

- **Site24x7** — alerts, down monitors, SLA risk
- **AWS SecurityHub** — new findings in the last 24h, severity breakdown, IAM/public-resource callouts
- **AWS Billing (Cost Explorer)** — spend today, month-to-date with prior-month comparison, quarter-to-date with QoQ pacing, forecast
- **Drata** — failing controls, overdue compliance tasks, upcoming audit deadlines
- **Gmail** — every message that hit the inbox in the last 24 hours
- **GitHub** — new/closed/stale PRs across configured orgs, plus the previous day's code volume (commits, repos touched, +/- lines)
- **Weather** — current conditions and today's outlook for a configured ZIP code
- **News** — multi-source RSS aggregator across BBC, CNN, Fox, NPR, Guardian, and AP, with cross-outlet deduplication to surface widely-covered stories
- **Stocks** — price, trend, and unusual-volume signals for a personal watchlist via `yfinance` (no API key), plus market-index context (S&P 500, Nasdaq, Dow, VIX)
- **Trump (Truth Social)** — posts from the last 24 hours via the free [trumpstruth.org](https://www.trumpstruth.org/) RSS feed

## Plugin architecture

Each data source is a self-contained folder under `plugins/<name>/`:

```
plugins/<name>/
├── plugin.py       # implements DataSourcePlugin (fetch + inference config)
├── auth.py         # plugin-owned authentication
├── prompt.md       # the LLM prompt used to summarize this source
├── chunker.py      # optional: custom map-reduce splitter
├── setup.py        # optional: one-time interactive setup (OAuth consent, etc.)
└── README.md
```

Plugins own everything about their source: the payload schema, the authentication flow, the prompt, the Groq temperature and token budget, the redaction rules, and the chunking strategy for oversized payloads. The core never inspects a payload — it's an opaque JSON blob that travels from `fetch()` through the summarizer to the LLM.

Adding a new source means dropping a folder into `plugins/`, implementing the `DataSourcePlugin` contract, adding env vars to `.env`, and listing the plugin name in `ENABLED_PLUGINS`. No core changes.

## Configuration

Everything lives in a single `.env` file mounted into the container. Plugin env vars are namespaced by plugin name (`SECURITYHUB_*`, `BILLING_AWS_*`, `GITHUB_*`, etc.) so plugins never read each other's config. AWS-backed plugins each get their own credential namespace, so SecurityHub and Billing can run against different accounts if desired (or share the same values — operator's call).

## Running it

The container is a one-shot: start it, it runs, it exits. How you invoke it is entirely up to you — cron, a scheduled ECS task, manual `docker run`, or any other trigger. This project ships:

- A `Dockerfile`
- A `docker-compose.yml` for local runs

No infrastructure-as-code, no CronJob manifests, no EventBridge rules. Those belong elsewhere.

Dry-run mode (`JARVIS_DRY_RUN=true`) prints the rendered digest to stdout instead of posting to Slack — useful for prompt iteration.

## Philosophy

A few principles drive the design:

- **Plugins own their world.** Schema, auth, prompt, temperature, redaction, chunking — all plugin-local. The core is infrastructure, not intelligence.
- **One-shot execution.** Jarvis doesn't know what time it is and doesn't need to. It runs when it's invoked, then exits.
- **Fail soft on sources, fail loud on config.** Missing env vars halt the run before any network call. A single source being down just means that section of the digest says "unavailable."
- **No state between runs.** No database, no cache, no history. Each run is independent.

## Full specification

See [`docs/specs/initial-spec.md`](docs/specs/initial-spec.md) for the complete design document: architecture, plugin contract, per-plugin details, error handling, security considerations, testing strategy, and future extensions.
