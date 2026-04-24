# Jarvis — Executive Summary Agent

Jarvis is a containerized Python service that performs a single one-shot run: on startup, it fetches the last 24 hours of activity from a configurable set of data-source plugins, runs each plugin's payload through Groq-hosted LLM inference with a per-plugin prompt, posts one consolidated executive brief to Slack, and exits.

The authoritative design document is [`docs/specs/initial-spec.md`](docs/specs/initial-spec.md). Read it before making non-trivial changes.

## Key Concepts

| Term | Meaning |
|------|---------|
| Plugin | A self-contained data source under `plugins/<name>/`. Owns its fetch, auth, payload schema, prompt, temperature, and redaction. |
| Payload | The raw JSON-serializable blob a plugin returns from `fetch()`. The core never inspects its shape. |
| Digest | The single Slack Block Kit message Jarvis posts per run. |
| Run | One invocation of the container from start to exit. Stateless; no data persists between runs. |
| Groq queue | An in-process `asyncio.Queue` with a token-bucket rate limiter that mediates all Groq API calls. |

## Project Structure

```
jarvis-executive-summary/
├── Dockerfile
├── docker-compose.yml
├── pyproject.toml
├── .env / .env.example
├── README.md
├── docs/
│   └── specs/
│       └── initial-spec.md      # authoritative design document
├── jarvis/                      # core (framework, not data sources)
│   ├── __main__.py              # container entrypoint
│   ├── config.py
│   ├── orchestrator.py
│   └── core/
│       ├── plugin.py            # DataSourcePlugin ABC + FetchResult
│       ├── loader.py
│       ├── groq_queue.py
│       ├── summarizer.py
│       ├── slack.py
│       ├── logging.py
│       ├── redaction.py         # optional helpers plugins may compose
│       └── auth/                # optional helpers: api_key, oauth2, aws
├── plugins/                     # one self-contained folder per source
│   ├── site24x7/ securityhub/ aws_billing/ drata/
│   ├── gmail/ github/ weather/
│   ├── news/ stocks/ trump/
│   └── ...
├── scripts/
│   └── dry_run.py               # end-to-end run that prints to stdout instead of Slack
└── tests/
```

## Core Design Principles

- **Plugins own their world.** Schema, auth, prompt, temperature, redaction, chunking — all plugin-local. The core is infrastructure, not intelligence.
- **One-shot execution.** No loop, no scheduler, no daemon. The container runs and exits.
- **Fail soft on sources, fail loud on config.** Missing env vars halt the run before any network call. A single source being down just means that section of the digest says "unavailable."
- **No state between runs.** No database, no cache, no history.
- **No infrastructure-as-code in this repo.** Deliverables are the Python app, `Dockerfile`, and `docker-compose.yml`. How the container gets invoked is the operator's concern.

## Working in this codebase

A short set of principles that save us from agent-flavored mistakes. When in doubt, bias toward the smaller change.

- **Write less code.** The best diff is a smaller diff. Before adding, look for existing code to delete, simplify, or reuse. Every line is a future maintenance cost.
- **Don't build for futures that don't exist.** The spec explicitly calls out what's out of scope (no broker, no scheduler, no database, no IaC). Don't add hooks, adapters, or extensibility points for anything on the "out" list. YAGNI.
- **Duplicate twice before abstracting.** Two plugins reaching for the same helper is fine. Three is a pattern. An abstraction invented to cover only two call sites is usually the wrong abstraction and painful to undo.
- **Follow the grain.** Before writing a new plugin or core module, find the closest analogous file in the repo and match its shape. If you think an existing pattern is wrong, raise it — don't silently diverge.
- **Don't delete what you don't understand.** If a line exists and its purpose isn't obvious, investigate before removing it. Chesterton's Fence applies even in a young codebase.
- **No silent scope creep.** Do what was asked. If you notice adjacent issues, call them out — don't bundle unrequested "improvements" into the same change.

When the spec and a principle conflict, the spec wins.

## Common Commands

```bash
# Local run (prints digest to stdout instead of posting to Slack)
JARVIS_DRY_RUN=true python -m jarvis

# Full run (posts to Slack)
python -m jarvis

# Docker
docker compose run --rm jarvis

# Tests
pytest

# Lint
ruff check .
```

## Conventions

Detailed standards live in modular rule files under `claude/rules/`:

| Rule File | What It Covers |
|-----------|----------------|
| `claude/rules/python.md` | Python 3.12 standards, async-by-default, docstrings, imports, exceptions |
| `claude/rules/logging.md` | `logging` module usage, levels, patterns, what to log per run |
| `claude/rules/data-structures.md` | When to reach for Pydantic, dataclass, TypedDict, SimpleNamespace |
| `claude/rules/testing.md` | pytest + pytest-asyncio layout, plugin contract tests, fixtures |
| `claude/rules/commits.md` | Conventional Commits format and allowed types |
| `claude/rules/pr-quality.md` | Placement, dependencies, imports, style; files never to commit |

When the spec (`docs/specs/initial-spec.md`) and a rule file disagree, the spec wins — it's the design-of-record. If you need to change a design decision, update the spec first, then the rule files.
