"""Plugin contract test — auto-discovers enabled plugins from test.env.

For each plugin listed in ENABLED_PLUGINS (test.env), verify it satisfies
the DataSourcePlugin interface. Plugin-specific fetch tests live alongside
their fixtures in plugins/<name>/fixtures/.
"""

import importlib
import inspect
import json
import os
from pathlib import Path

import pytest

from jarvis.core.plugin import DataSourcePlugin


def _discover_plugin_classes() -> list[tuple[str, type]]:
    enabled = [p.strip() for p in os.environ.get("ENABLED_PLUGINS", "").split(",") if p.strip()]
    results = []
    for name in enabled:
        module_path = f"plugins.{name}.plugin"
        try:
            mod = importlib.import_module(module_path)
        except ImportError:
            continue
        for attr in vars(mod).values():
            if (
                isinstance(attr, type)
                and issubclass(attr, DataSourcePlugin)
                and attr is not DataSourcePlugin
            ):
                results.append((name, attr))
    return results


_PLUGIN_CLASSES = _discover_plugin_classes()


@pytest.mark.parametrize("name,cls", _PLUGIN_CLASSES)
def test_plugin_has_required_attributes(name, cls):
    instance = cls()
    assert isinstance(instance.name, str) and instance.name
    assert isinstance(instance.display_name, str) and instance.display_name
    assert isinstance(instance.required_env_vars, list)
    assert isinstance(instance.temperature, float)
    assert isinstance(instance.max_tokens, int)


@pytest.mark.parametrize("name,cls", _PLUGIN_CLASSES)
def test_plugin_fetch_is_coroutine(name, cls):
    instance = cls()
    assert inspect.iscoroutinefunction(instance.fetch)


@pytest.mark.parametrize("name,cls", _PLUGIN_CLASSES)
def test_plugin_redact_is_identity_by_default(name, cls):
    instance = cls()
    payload = {"test": "value", "nested": [1, 2, 3]}
    result = instance.redact(payload)
    # Must return same outer type
    assert type(result) is type(payload)


@pytest.mark.parametrize("name,cls", _PLUGIN_CLASSES)
def test_plugin_prompt_template_loads(name, cls):
    instance = cls()
    template = instance.prompt_template()
    assert isinstance(template, str) and len(template) > 10
    assert "{{ payload }}" in template
