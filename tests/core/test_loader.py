"""Tests for jarvis.core.loader."""

import pytest

from jarvis.core.exceptions import ConfigError
from jarvis.core.loader import load_plugins


def test_empty_enabled_plugins_returns_empty_list():
    assert load_plugins([]) == []


def test_missing_plugin_directory_raises_config_error():
    with pytest.raises(ConfigError, match="Plugin directory not found"):
        load_plugins(["nonexistent_plugin"])
