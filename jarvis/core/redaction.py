"""Shared regex-based redaction helpers plugins may compose."""

import re
from typing import Any

__all__ = [
    "redact_aws_keys",
    "redact_bearer_tokens",
    "redact_jwts",
    "redact_string",
]

_AWS_KEY_RE = re.compile(r"(?:AKIA|ASIA|AROA|AIDA)[A-Z0-9]{16}")
_BEARER_RE = re.compile(r"Bearer\s+[A-Za-z0-9\-._~+/]+=*", re.IGNORECASE)
_JWT_RE = re.compile(r"eyJ[A-Za-z0-9\-_]+\.eyJ[A-Za-z0-9\-_]+\.[A-Za-z0-9\-_]+")


def redact_string(text: str) -> str:
    """Replace known secret patterns in a string with placeholder text."""
    text = _AWS_KEY_RE.sub("[REDACTED_AWS_KEY]", text)
    text = _BEARER_RE.sub("Bearer [REDACTED]", text)
    text = _JWT_RE.sub("[REDACTED_JWT]", text)
    return text


def redact_aws_keys(payload: Any) -> Any:
    """Walk a JSON-serializable structure and redact AWS key patterns."""
    return _walk(payload, _AWS_KEY_RE, "[REDACTED_AWS_KEY]")


def redact_bearer_tokens(payload: Any) -> Any:
    """Walk a JSON-serializable structure and redact Bearer token patterns."""
    return _walk(payload, _BEARER_RE, "Bearer [REDACTED]")


def redact_jwts(payload: Any) -> Any:
    """Walk a JSON-serializable structure and redact JWT patterns."""
    return _walk(payload, _JWT_RE, "[REDACTED_JWT]")


def _walk(node: Any, pattern: re.Pattern, replacement: str) -> Any:
    if isinstance(node, str):
        return pattern.sub(replacement, node)
    if isinstance(node, dict):
        return {k: _walk(v, pattern, replacement) for k, v in node.items()}
    if isinstance(node, list):
        return [_walk(item, pattern, replacement) for item in node]
    return node
