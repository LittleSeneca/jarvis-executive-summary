# Jarvis — Executive Summary Agent

A containerized Python tool that pulls the last 24 hours of activity from a configurable set of data sources, summarizes each through Groq-hosted LLM inference, and posts a single consolidated executive brief to Slack — then exits.

One container, one run, one well-formatted morning digest. No daemon, no scheduler, no loop.

## Sample output

> **Jarvis — Morning Brief — Friday, April 25 2026**
> *Run completed in 15.7s · 10 plugins succeeded · 0 failed*
>
> ---
>
> :shield: **Security** — 6 CRITICAL findings for CVE-2026-XXXXX require same-day remediation across 3 affected services.
>
> :white_check_mark: **Compliance** — 9 of 50 monitors failing in Drata, including 2 HIGH-priority failures: *Employees Have Unique Email Accounts* and *MFA on Identity Provider*.
>
> :globe_with_meridians: **Infrastructure** — 50 malicious URLs and 4 new KEV entries tracked in the last 24 hours. Dominant malware families: ClearFake, Mozi, QuasarRAT.
>
> :email: **Email** — VendorCloud monitoring requires attention due to 3 critical CPU utilization alerts. A. Chen and J. Rivera are awaiting responses.
>
> :chart_with_upwards_trend: **Market** — NVDA had a significant single-day move of +4.75% and is near its 52-week high (52w position: 0.97).
>
> :newspaper: **Geopolitics** — Developing situation in the Middle East and heightened shipping-lane tensions could affect US business operations and global markets today.
>
> :bust_in_silhouette: **Personnel** — J. Smith requires attention for policy acknowledgment, MFA enrollment, and 2 other open compliance items.
>
> :partly_sunny: **Weather** — Expect mainly clear conditions today with a chilly temperature, turning overcast by end of day and continuing into tomorrow.
> - Current: 45°, feels like 40° — Mainly clear, humidity 40%, wind 4 mph
> - Today: high 49° / low 30°, 1% chance of precipitation — :cloud: Overcast
> - Tomorrow: high 50° / low 32°, 3% chance of precipitation — :cloud: Overcast

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

### Locally

```bash
# Dry run — prints the digest to stdout instead of posting to Slack
JARVIS_DRY_RUN=true python -m jarvis

# Full run via Docker Compose
docker compose run --rm jarvis
```

### In AWS (production)

The `terraform/` directory contains everything needed to run Jarvis on a daily schedule in AWS. The setup has three moving parts:

**1. Image builds (GitHub Actions)**  
Every commit to a pull request builds the Docker image as an acceptance check. Merging to `main` builds and pushes it to the public GitHub Container Registry (`ghcr.io/littleseneca/jarvis-executive-summary:latest`). No AWS credentials are needed in CI — the image contains no secrets.

**2. Secrets (AWS SSM Parameter Store)**  
All credentials from your local `.env` are synced to SSM Parameter Store under `/jarvis/<VAR_NAME>` as `SecureString` entries. This happens automatically on `terraform apply` whenever `.env` changes. The ECS task fetches them at launch and injects them as environment variables — the container image itself stays secret-free.

**3. Scheduled execution (AWS EventBridge + ECS Fargate)**  
An EventBridge Scheduler fires on a configurable timezone-aware cron and calls ECS `RunTask`. Fargate pulls the latest image from ghcr.io, fetches secrets from SSM, runs the container, and exits. There is no standing compute — you only pay for the ~5 minutes the task runs (~$0.12/month at the default sizing).

```
ghcr.io ──pull── ECS Fargate task ──reads── SSM Parameter Store
                       │
                  posts digest
                       │
                     Slack
```

**First-time deploy:**

```bash
cd terraform
cp terraform.tfvars.example terraform.tfvars   # fill in region, VPC, subnets, schedule
terraform init
terraform apply                                 # creates all AWS resources + syncs .env to SSM
terraform output manual_run_command             # get a one-off run command for testing
```

**Triggering a manual run:**

```bash
terraform -chdir=terraform output -raw manual_run_command | bash
```

**Watching logs:**

```bash
aws logs tail /aws/jarvis/run-logs --follow --region <your-region>
```

See [`terraform/terraform.tfvars.example`](terraform/terraform.tfvars.example) for all configurable options (region, schedule time and timezone, VPC/subnet targeting, CPU/memory sizing).  
See [`docs/specs/infrastructure-spec.md`](docs/specs/infrastructure-spec.md) for the full infrastructure design document.

Dry-run mode (`JARVIS_DRY_RUN=true`) prints the rendered digest to stdout instead of posting to Slack — useful for prompt iteration.

## Philosophy

A few principles drive the design:

- **Plugins own their world.** Schema, auth, prompt, temperature, redaction, chunking — all plugin-local. The core is infrastructure, not intelligence.
- **One-shot execution.** Jarvis doesn't know what time it is and doesn't need to. It runs when it's invoked, then exits.
- **Fail soft on sources, fail loud on config.** Missing env vars halt the run before any network call. A single source being down just means that section of the digest says "unavailable."
- **No state between runs.** No database, no cache, no history. Each run is independent.

## Full specification

See [`docs/specs/initial-spec.md`](docs/specs/initial-spec.md) for the complete design document: architecture, plugin contract, per-plugin details, error handling, security considerations, testing strategy, and future extensions.
