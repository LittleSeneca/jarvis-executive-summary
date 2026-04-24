---
paths:
  - "**/*.py"
---

# Logging

Use the standard library `logging` module. Do not use `print()` for operational output in application code.

Jarvis runs as a containerized one-shot process and writes logs to stdout in structured JSON form (see spec §9). The core is responsible for configuring the handler and JSON formatter once at startup; individual modules just use a logger named after their module path.

## Logger Name

Always use `log` (not `logger`) as the variable name, initialized with the module's `__name__`:

```python
import logging

log = logging.getLogger(__name__)
```

## Log Levels

- `log.info()` — Successful operations worth noting (plugin completed, posted to Slack, Groq call finished).
- `log.warning()` — Recoverable issues (missing optional config, retrying after 429, partial plugin failure).
- `log.exception()` — Caught exceptions with full traceback (always inside an `except` block).
- `log.error()` — Failures that don't have an exception context (e.g. a plugin returned malformed data).
- `log.debug()` — Verbose diagnostics for development; off by default in production.

## Patterns

```python
# Caught exception — use log.exception for automatic traceback
try:
    client.connect()
except Exception:
    log.exception("Failed to connect to service")

# Warning for degraded but functional state
if not is_configured():
    log.warning("Service credentials not configured — skipping init")

# Info for noteworthy success
log.info("Successfully authenticated with %s", service_name)
```

Use `%s` style formatting in log calls (not f-strings) to allow lazy interpolation and to keep structured-log fields clean.

## What to Log Per Run

The orchestrator should log (in addition to whatever each plugin logs):

- Run start with the enabled plugin list
- Per-plugin fetch duration and result status
- Groq total tokens consumed and request count
- Slack post latency
- Total run duration and exit code

These become the breadcrumbs for diagnosing a bad morning brief after the fact.

## Rule of Silence

If a log line doesn't carry information, don't write it. Don't log that a function was entered, that a loop started, or that a value was assigned — the stack trace and the logs that matter already tell you those things. A run that produces a dozen meaningful log lines is easier to read than one that produces a thousand noisy ones. When in doubt, drop to `log.debug()` rather than `log.info()`.

