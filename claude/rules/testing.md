---
paths:
  - "tests/**/*.py"
  - "**/test_*.py"
  - "conftest.py"
---

# Testing

Use `pytest` with `pytest-asyncio` for async coroutine tests. Test files follow `test_<module>.py` naming.

## Layout

Mirror the source layout:

```
tests/
├── conftest.py                # shared fixtures (mock Groq, mock Slack, env loader)
├── core/
│   ├── test_loader.py
│   ├── test_groq_queue.py
│   ├── test_summarizer.py
│   └── test_slack.py
└── plugins/
    ├── test_plugin_contract.py    # every plugin is run through the DataSourcePlugin contract
    ├── site24x7/
    │   └── test_site24x7.py
    ├── github/
    │   └── test_github.py
    └── ...
```

Put plugin-specific fixtures (recorded API responses) inside `plugins/<name>/fixtures/` alongside the plugin, not in the test tree.

## Core Fixtures

Shared fixtures belong in the top-level `conftest.py`:

- **`mock_groq`** — an in-memory stand-in for the Groq client that returns canned markdown summaries. Tests should never hit the real Groq API.
- **`mock_slack`** — captures `chat.postMessage` calls into a list; tests assert against the captured payload.
- **`test_env`** — loads a `tests/fixtures/test.env` so `config.py` has all required vars when tests import it.
- **`frozen_time`** — pins `datetime.utcnow()` so date-window logic is deterministic.

## Plugin Contract Test

Every plugin must pass a shared contract test that:

1. Instantiates the plugin with mock env vars
2. Verifies it satisfies the `DataSourcePlugin` interface (required attributes present, `fetch` is a coroutine, `redact` returns a payload of the same outer type)
3. Runs `fetch()` against a recorded fixture and asserts the payload is JSON-serializable
4. Runs the plugin's prompt template against the fixture and confirms it renders

This lives in `tests/plugins/test_plugin_contract.py` and auto-discovers every plugin in `ENABLED_PLUGINS` from `tests/fixtures/test.env`.

## Per-Plugin Integration Tests

Each plugin has its own test module that runs the full `fetch → redact → summarize (mocked Groq) → format` pipeline against a recorded fixture in `plugins/<name>/fixtures/`. This is the suite that catches "I changed the plugin and something broke" regressions.

## Async Tests

Mark async tests with `pytest-asyncio`:

```python
import pytest

@pytest.mark.asyncio
async def test_fetch_returns_expected_shape(mock_httpx):
    plugin = GithubPlugin()
    result = await plugin.fetch(window_hours=24)
    assert result.source_name == "GitHub"
    assert "prs" in result.raw_payload
```

Or configure `asyncio_mode = "auto"` in `pyproject.toml` so every `async def` test is treated as async without the marker.

## Markers

- **`@pytest.mark.slow`** — tests that hit the real network or take > 1s. Skipped in default CI; run with `pytest -m slow` for the full pipeline against live APIs.
- **`@pytest.mark.livedata`** — requires real credentials in `.env`. Used for the `dry_run.py` smoke test, not typical CI.

## What Not to Test

- Don't test Groq's output quality in unit tests — that's what the dry-run + a human reviewer are for.
- Don't test rate-limiter timing precisely; test the token-bucket math and retry behavior separately.
