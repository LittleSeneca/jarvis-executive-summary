"""Async Groq inference queue with token-bucket rate limiting."""

import asyncio
import logging
import math
import random
import time
from dataclasses import dataclass, field
from typing import Any

from jarvis.core.exceptions import GroqError

__all__ = ["InferenceJob", "GroqQueue"]

log = logging.getLogger(__name__)


@dataclass(slots=True)
class InferenceJob:
    plugin_name: str
    prompt: str
    model: str
    temperature: float
    max_tokens: int
    result: asyncio.Future = field(default_factory=lambda: asyncio.get_event_loop().create_future())


class _TokenBucket:
    """Leaky-bucket rate limiter for requests and tokens per minute."""

    def __init__(self, requests_per_minute: int, tokens_per_minute: int) -> None:
        self._rpm = requests_per_minute
        self._tpm = tokens_per_minute
        self._req_tokens = float(requests_per_minute)
        self._tok_tokens = float(tokens_per_minute)
        self._last = time.monotonic()

    def _refill(self) -> None:
        now = time.monotonic()
        elapsed = now - self._last
        self._last = now
        self._req_tokens = min(self._rpm, self._req_tokens + elapsed * self._rpm / 60)
        self._tok_tokens = min(self._tpm, self._tok_tokens + elapsed * self._tpm / 60)

    async def acquire(self, estimated_tokens: int) -> None:
        """Block until a request slot and token budget are available."""
        while True:
            self._refill()
            if self._req_tokens >= 1 and self._tok_tokens >= estimated_tokens:
                self._req_tokens -= 1
                self._tok_tokens -= estimated_tokens
                return
            await asyncio.sleep(0.25)


class GroqQueue:
    """Mediate all Groq API calls through a rate-limited async queue."""

    def __init__(
        self,
        api_key: str,
        default_model: str,
        requests_per_minute: int = 30,
        tokens_per_minute: int = 60_000,
        worker_concurrency: int = 2,
        max_retries: int = 4,
    ) -> None:
        self._api_key = api_key
        self._default_model = default_model
        self._max_retries = max_retries
        self._bucket = _TokenBucket(requests_per_minute, tokens_per_minute)
        self._queue: asyncio.Queue[InferenceJob] = asyncio.Queue()
        self._workers: list[asyncio.Task] = []
        self._concurrency = worker_concurrency
        self._total_tokens = 0
        self._total_requests = 0

    async def __aenter__(self) -> "GroqQueue":
        for _ in range(self._concurrency):
            self._workers.append(asyncio.create_task(self._worker()))
        return self

    async def __aexit__(self, *_: Any) -> None:
        await self._queue.join()
        for w in self._workers:
            w.cancel()
        await asyncio.gather(*self._workers, return_exceptions=True)

    async def submit(self, job: InferenceJob) -> str:
        """Enqueue a job and await its result."""
        await self._queue.put(job)
        return await job.result

    async def _worker(self) -> None:
        while True:
            job = await self._queue.get()
            try:
                result = await self._call_groq(job)
                job.result.set_result(result)
            except Exception as exc:
                job.result.set_exception(exc)
            finally:
                self._queue.task_done()

    async def _call_groq(self, job: InferenceJob) -> str:
        from groq import AsyncGroq, RateLimitError

        client = AsyncGroq(api_key=self._api_key)
        estimated_tokens = math.ceil(len(job.prompt) / 4) + job.max_tokens

        for attempt in range(self._max_retries + 1):
            await self._bucket.acquire(estimated_tokens)
            try:
                response = await client.chat.completions.create(
                    model=job.model,
                    messages=[{"role": "user", "content": job.prompt}],
                    temperature=job.temperature,
                    max_tokens=job.max_tokens,
                )
                content = response.choices[0].message.content or ""
                usage = response.usage
                if usage:
                    self._total_tokens += usage.total_tokens
                self._total_requests += 1
                log.info(
                    "Groq call complete: plugin=%s tokens=%s attempt=%s",
                    job.plugin_name,
                    usage.total_tokens if usage else "?",
                    attempt,
                )
                return content
            except RateLimitError:
                if attempt == self._max_retries:
                    raise GroqError(f"Groq rate-limit exceeded for plugin '{job.plugin_name}'")
                backoff = (2**attempt) + random.uniform(0, 1)
                log.warning("Groq 429 for plugin %s, backing off %.1fs", job.plugin_name, backoff)
                await asyncio.sleep(backoff)
            except Exception as exc:
                raise GroqError(f"Groq error for plugin '{job.plugin_name}': {exc}") from exc

        raise GroqError(f"Groq failed after {self._max_retries} retries for '{job.plugin_name}'")

    @property
    def total_tokens(self) -> int:
        return self._total_tokens

    @property
    def total_requests(self) -> int:
        return self._total_requests
