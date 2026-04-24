"""Shared fixtures for all tests."""

import os
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest


@pytest.fixture(autouse=True)
def test_env(monkeypatch):
    """Load tests/fixtures/test.env into the environment."""
    env_path = Path(__file__).parent / "fixtures" / "test.env"
    for line in env_path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        monkeypatch.setenv(key.strip(), value.strip())


@pytest.fixture
def mock_groq():
    """Return a callable that patches GroqQueue.submit with canned markdown."""
    canned = "### Test Source\n_Test headline_\n\n- Bullet one\n- Bullet two\n"

    async def _submit(self, job):
        return canned

    return _submit


@pytest.fixture
def mock_slack():
    """Capture chat.postMessage calls."""
    calls = []

    async def _post(*args, **kwargs):
        calls.append(kwargs)

    return calls, _post
