"""Tests for jarvis.core.summarizer chunking logic."""

import pytest

from jarvis.core.summarizer import default_chunker


def test_default_chunker_splits_list():
    payload = [{"id": 1}, {"id": 2}, {"id": 3}]
    chunks = default_chunker(payload)
    assert chunks == payload


def test_default_chunker_wraps_non_list():
    payload = {"key": "value"}
    chunks = default_chunker(payload)
    assert chunks == [payload]


def test_default_chunker_wraps_string():
    chunks = default_chunker("raw text")
    assert chunks == ["raw text"]
