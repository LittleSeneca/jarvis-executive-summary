"""Authentication for the SecurityHub plugin."""

from typing import Any

from jarvis.core.auth.aws import boto3_client

__all__ = ["get_client"]


async def get_client() -> Any:
    """Return a boto3 securityhub client using SECURITYHUB-prefixed env vars."""
    return await boto3_client("SECURITYHUB", "securityhub")
