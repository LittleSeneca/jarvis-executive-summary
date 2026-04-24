"""Project exception hierarchy."""

__all__ = [
    "ConfigError",
    "PluginError",
    "PluginFetchError",
    "PluginAuthError",
    "GroqError",
    "SlackDeliveryError",
]


class ConfigError(Exception):
    """Raise for invalid or missing env var detected at startup."""


class PluginError(Exception):
    """Base class for all plugin-originated failures."""


class PluginFetchError(PluginError):
    """Raise when a plugin's fetch() fails."""


class PluginAuthError(PluginFetchError):
    """Raise when credentials are missing or rejected."""


class GroqError(Exception):
    """Raise when a Groq call fails after retries."""


class SlackDeliveryError(Exception):
    """Raise when chat.postMessage fails after retries."""
