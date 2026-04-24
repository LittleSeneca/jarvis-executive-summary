"""Custom chunker for the AWS Billing plugin.

The billing payload is a dict of sections rather than a list, so the default
list-splitter is not appropriate. This chunker returns each top-level section
(today, mtd, qtd, forecast) as its own partial dict so the map-reduce path in
the summarizer can handle oversized payloads gracefully.
"""

from typing import Any

__all__ = ["billing_chunker"]

_SECTIONS = ("today", "mtd", "qtd", "forecast")


def billing_chunker(payload: Any) -> list[Any]:
    """Split the billing payload into one chunk per section.

    Each chunk is a dict containing only that section so the prompt template
    can render it in isolation.
    """
    if not isinstance(payload, dict):
        return [payload]

    chunks = []
    for section in _SECTIONS:
        if section in payload:
            chunks.append({section: payload[section]})

    # Fallback: return the whole payload as a single chunk
    return chunks if chunks else [payload]
