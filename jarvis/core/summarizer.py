"""Render prompts and submit inference jobs to the Groq queue."""

import json
import logging
from datetime import datetime, timezone
from typing import Any

from jinja2 import Template

from jarvis.core.exceptions import GroqError
from jarvis.core.groq_queue import GroqQueue, InferenceJob
from jarvis.core.plugin import DataSourcePlugin, FetchResult

__all__ = ["summarize", "default_chunker"]

log = logging.getLogger(__name__)

# Rough chars-per-token estimate; good enough for chunking decisions
_CHARS_PER_TOKEN = 4
# Leave headroom for the prompt template overhead
_CONTEXT_LIMIT_TOKENS = 28_000


def default_chunker(payload: Any) -> list[Any]:
    """Split a top-level JSON array into individual elements.

    If payload is not a list, return it as a single-element list.
    """
    if isinstance(payload, list):
        return payload
    return [payload]


def _render(template_str: str, payload: Any, metadata: dict, window_hours: int) -> str:
    tpl = Template(template_str)
    return tpl.render(
        payload=json.dumps(payload, default=str),
        metadata=json.dumps(metadata, default=str),
        window_hours=window_hours,
        today=datetime.now(timezone.utc).strftime("%Y-%m-%d"),
    )


def _estimate_tokens(text: str) -> int:
    return len(text) // _CHARS_PER_TOKEN


async def summarize(
    plugin: DataSourcePlugin,
    result: FetchResult,
    queue: GroqQueue,
    default_model: str,
    window_hours: int,
) -> str:
    """Redact, render, chunk if needed, submit to Groq, return markdown summary."""
    redacted = plugin.redact(result.raw_payload)
    template_str = plugin.prompt_template()
    model = plugin.model_override or default_model

    full_prompt = _render(template_str, redacted, result.metadata, window_hours)
    token_estimate = _estimate_tokens(full_prompt)

    if token_estimate <= _CONTEXT_LIMIT_TOKENS:
        return await _submit(plugin, full_prompt, model, queue)

    # Map-reduce: summarize each chunk, then summarize the summaries
    log.warning(
        "Payload for '%s' estimated %d tokens — using map-reduce chunking",
        plugin.name,
        token_estimate,
    )
    chunker = plugin.chunker()
    chunks = chunker(redacted)

    chunk_summaries: list[str] = []
    for i, chunk in enumerate(chunks):
        chunk_prompt = _render(template_str, chunk, result.metadata, window_hours)
        try:
            summary = await _submit(plugin, chunk_prompt, model, queue)
            chunk_summaries.append(summary)
        except GroqError:
            log.warning("Chunk %d/%d for '%s' failed, skipping", i + 1, len(chunks), plugin.name)

    if not chunk_summaries:
        raise GroqError(f"All chunks failed for plugin '{plugin.name}'")

    reduce_prompt = (
        f"Combine the following partial summaries for '{plugin.display_name}' into one "
        f"cohesive summary following the standard output format:\n\n"
        + "\n\n---\n\n".join(chunk_summaries)
    )
    return await _submit(plugin, reduce_prompt, model, queue)


async def _submit(plugin: DataSourcePlugin, prompt: str, model: str, queue: GroqQueue) -> str:
    job = InferenceJob(
        plugin_name=plugin.name,
        prompt=prompt,
        model=model,
        temperature=plugin.temperature,
        max_tokens=plugin.max_tokens,
    )
    return await queue.submit(job)
