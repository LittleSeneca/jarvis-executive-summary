"""Discover and validate enabled plugins."""

import importlib
import logging
import os
from pathlib import Path
from typing import TYPE_CHECKING

from jarvis.core.exceptions import ConfigError
from jarvis.core.plugin import DataSourcePlugin

if TYPE_CHECKING:
    pass

__all__ = ["load_plugins"]

log = logging.getLogger(__name__)

_PLUGINS_ROOT = Path(__file__).parent.parent.parent / "plugins"


def load_plugins(enabled: list[str]) -> list[DataSourcePlugin]:
    """Discover, import, instantiate, and validate enabled plugins.

    Raises ConfigError if any enabled plugin is missing required env vars.
    """
    plugins: list[DataSourcePlugin] = []
    for name in enabled:
        plugin = _load_one(name)
        _validate_env(plugin)
        plugins.append(plugin)
        log.info("Loaded plugin: %s", name)
    return plugins


def _load_one(name: str) -> DataSourcePlugin:
    plugin_dir = _PLUGINS_ROOT / name
    if not plugin_dir.is_dir():
        raise ConfigError(f"Plugin directory not found: plugins/{name}")

    module_path = f"plugins.{name}.plugin"
    try:
        mod = importlib.import_module(module_path)
    except ImportError as exc:
        raise ConfigError(f"Cannot import plugin '{name}': {exc}") from exc

    # Find the DataSourcePlugin subclass in the module
    cls = None
    for attr in vars(mod).values():
        if (
            isinstance(attr, type)
            and issubclass(attr, DataSourcePlugin)
            and attr is not DataSourcePlugin
        ):
            cls = attr
            break

    if cls is None:
        raise ConfigError(f"Plugin '{name}' has no DataSourcePlugin subclass in plugin.py")

    return cls()


def _validate_env(plugin: DataSourcePlugin) -> None:
    missing = [v for v in plugin.required_env_vars if not os.environ.get(v)]
    if missing:
        raise ConfigError(
            f"Plugin '{plugin.name}' is missing required env vars: {', '.join(missing)}"
        )
