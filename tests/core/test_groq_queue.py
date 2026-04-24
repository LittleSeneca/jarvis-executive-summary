"""Tests for jarvis.core.groq_queue."""

import asyncio

import pytest

from jarvis.core.groq_queue import InferenceJob, _TokenBucket


def test_token_bucket_acquires_immediately_when_full():
    bucket = _TokenBucket(requests_per_minute=60, tokens_per_minute=100_000)

    async def _run():
        await bucket.acquire(100)

    asyncio.run(_run())


def test_token_bucket_refills_over_time():
    bucket = _TokenBucket(requests_per_minute=60, tokens_per_minute=100_000)
    # Drain the bucket
    bucket._req_tokens = 0
    bucket._tok_tokens = 0
    # Simulate 1 second of elapsed time
    import time
    bucket._last = time.monotonic() - 1.0
    bucket._refill()
    assert bucket._req_tokens == pytest.approx(1.0, abs=0.05)
    assert bucket._tok_tokens == pytest.approx(100_000 / 60, abs=10)


async def test_inference_job_future_resolves():
    job = InferenceJob(
        plugin_name="test",
        prompt="Hello",
        model="llama-3.3-70b-versatile",
        temperature=0.2,
        max_tokens=100,
    )
    job.result.set_result("ok")
    assert await job.result == "ok"
