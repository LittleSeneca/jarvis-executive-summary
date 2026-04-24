"""Boto3 session builder that honours plugin-namespaced env vars."""

import asyncio
import os
from typing import Any

__all__ = ["build_boto3_session", "boto3_client"]


def build_boto3_session(prefix: str):
    """Build a boto3.Session from env vars prefixed with `prefix`.

    Looks for <PREFIX>_AWS_ACCESS_KEY_ID, <PREFIX>_AWS_SECRET_ACCESS_KEY,
    <PREFIX>_AWS_REGION, and optionally <PREFIX>_AWS_PROFILE.
    """
    import boto3

    profile = os.environ.get(f"{prefix}_AWS_PROFILE")
    if profile:
        return boto3.Session(profile_name=profile)

    return boto3.Session(
        aws_access_key_id=os.environ.get(f"{prefix}_AWS_ACCESS_KEY_ID"),
        aws_secret_access_key=os.environ.get(f"{prefix}_AWS_SECRET_ACCESS_KEY"),
        region_name=os.environ.get(f"{prefix}_AWS_REGION", "us-east-1"),
    )


async def boto3_client(prefix: str, service: str) -> Any:
    """Return a boto3 low-level client, constructed off the event loop."""
    session = await asyncio.to_thread(build_boto3_session, prefix)
    return await asyncio.to_thread(session.client, service)
