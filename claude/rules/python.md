---
paths:
  - "**/*.py"
---

# Python Standards

Target Python 3.12. `from __future__ import annotations` is acceptable when needed for forward references but should not be used as a blanket default.

## Async by Default

Jarvis is an async application — plugins fetch concurrently, the Groq queue is an `asyncio.Queue`, and the orchestrator uses `asyncio.gather`. Prefer `async def` and `httpx.AsyncClient` over their synchronous equivalents. Only drop to sync code when a library leaves no choice (e.g. `boto3`), and in that case run it inside `asyncio.to_thread` rather than blocking the event loop.

## Docstrings

Write PEP 257 compliant docstrings. The first line must be imperative. Multi-line docstrings are appropriate when additional detail is needed — add a blank line after the summary, then continue:

```python
# GOOD — single-line
def get_client() -> httpx.AsyncClient | None:
    """Return the singleton HTTP client, creating it lazily."""

# GOOD — multi-line when extra context is needed
async def fetch(window_hours: int) -> FetchResult:
    """Pull the last `window_hours` of activity from the source.

    Must be idempotent — may be retried by the orchestrator on transient
    failure.
    """

# BAD — descriptive instead of imperative
def get_client() -> httpx.AsyncClient | None:
    """Returns the singleton HTTP client."""

# BAD — redundant Args/Returns blocks
def get_client() -> httpx.AsyncClient | None:
    """Return the singleton HTTP client.

    Returns:
        The client instance or None.
    """
```

Do not repeat argument names, types, or return values in extended docstrings — use type annotations instead. Only add extended documentation when functionality or parameters are unintuitive.

## Module Exports

Module-level functions should not use leading underscores for "privacy." Instead, define `__all__` at the top of the module listing the public API. Functions scoped inside a class or another function may be private:

```python
__all__ = [
    "DataSourcePlugin",
    "FetchResult",
    "RunReport",
]
```

## Exceptions

Define a small project exception hierarchy in `jarvis/core/exceptions.py` and use those over generic `ValueError` / `RuntimeError` for flow-control errors. Plugins define their own local exception types inside their folder when the failure is plugin-specific (e.g. `plugins/gmail/exceptions.py` for OAuth-refresh failures).

Core exception taxonomy (starting set — grow as needed):

| Exception | When to use |
|-----------|-------------|
| `ConfigError` | Invalid or missing env var detected at startup. Hard-fails the run. |
| `PluginError` | Base class for all plugin-originated failures. |
| `PluginFetchError` | A plugin's `fetch()` failed. Caught by orchestrator; plugin is marked failed but the digest still ships. |
| `PluginAuthError` | Credentials missing or rejected. Subclass of `PluginFetchError`. |
| `GroqError` | Groq call failed after retries. Caught by summarizer; affected section shows "summary unavailable." |
| `SlackDeliveryError` | `chat.postMessage` failed after retries. Triggers stdout fallback. |

Raise these so the orchestrator and error handlers can reason about what happened and decide whether to degrade gracefully or abort.

## Imports

- Use top-level imports. Only use lazy imports (inside functions) to break circular dependencies.
- If a package is a declared dependency, import it at the top level — do not guard with `try/except ImportError`.
- Use `# noqa: PLC0415` only when a lazy import is genuinely required.

## Parameter Defaults

Prefer the `or` chain pattern over verbose ternaries:

```python
# GOOD
effective_model = plugin.model_override or settings.groq_model or "llama-3.3-70b-versatile"

# BAD
effective_model = (
    plugin.model_override
    if plugin.model_override is not None
    else (settings.groq_model or "llama-3.3-70b-versatile")
)
```
