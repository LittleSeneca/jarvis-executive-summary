"""Container entrypoint — runs once and exits."""

import asyncio
import sys

from jarvis.config import get_settings
from jarvis.core.exceptions import ConfigError
from jarvis.core.groq_queue import GroqQueue
from jarvis.core.loader import load_plugins
from jarvis.core.logging import configure_logging
from jarvis.orchestrator import run


async def _main() -> None:
    settings = get_settings()
    configure_logging(settings.log_level)

    plugins = load_plugins(settings.plugin_names)

    queue = GroqQueue(
        api_key=settings.groq_api_key,
        default_model=settings.groq_model,
        requests_per_minute=settings.groq_requests_per_minute,
        tokens_per_minute=settings.groq_tokens_per_minute,
        worker_concurrency=settings.groq_worker_concurrency,
        max_retries=settings.groq_max_retries,
    )

    await run(plugins, queue, settings)


def main() -> None:
    try:
        asyncio.run(_main())
    except ConfigError as exc:
        print(f"FATAL: {exc}", file=sys.stderr)
        sys.exit(1)
    except KeyboardInterrupt:
        sys.exit(0)


if __name__ == "__main__":
    main()
