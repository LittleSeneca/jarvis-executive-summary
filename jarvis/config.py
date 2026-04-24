"""Load and validate configuration from environment / .env file."""

from pydantic import Field, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from jarvis.core.exceptions import ConfigError

__all__ = ["Settings", "get_settings"]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # Core — stored as raw CSV string; pydantic-settings v2 JSON-parses list[str]
    # fields which breaks "weather,news,stocks" syntax. Split at the call site instead.
    enabled_plugins: str = ""
    log_level: str = "INFO"
    run_window_hours: int = 24
    jarvis_dry_run: bool = False

    # Groq
    groq_api_key: str
    groq_model: str = "llama-3.3-70b-versatile"
    groq_requests_per_minute: int = 30
    groq_tokens_per_minute: int = 60_000
    groq_worker_concurrency: int = 2
    groq_max_retries: int = 4

    # Slack — all optional; omitting SLACK_BOT_TOKEN writes digest to a markdown file instead
    slack_bot_token: str | None = None
    slack_target_type: str = "user"
    slack_target_id: str | None = None
    slack_username: str = "Jarvis"
    slack_icon_emoji: str = ":robot_face:"
    jarvis_output_dir: str = "/app/output"  # directory for markdown output; bind-mounted locally
    jarvis_output_file: str | None = None  # override full path; takes precedence over jarvis_output_dir

    @field_validator("slack_target_type")
    @classmethod
    def _validate_target_type(cls, v: str) -> str:
        if v and v not in {"user", "channel"}:
            raise ValueError("SLACK_TARGET_TYPE must be 'user' or 'channel'")
        return v

    @model_validator(mode="after")
    def _require_plugins(self) -> "Settings":
        if not self.plugin_names:
            raise ConfigError("ENABLED_PLUGINS must list at least one plugin")
        return self

    @property
    def plugin_names(self) -> list[str]:
        """Return ENABLED_PLUGINS split into a list, stripping whitespace."""
        return [p.strip() for p in self.enabled_plugins.split(",") if p.strip()]


_settings: Settings | None = None


def get_settings() -> Settings:
    """Return the singleton Settings instance, creating it on first call."""
    global _settings
    if _settings is None:
        try:
            _settings = Settings()  # type: ignore[call-arg]
        except Exception as exc:
            raise ConfigError(f"Configuration error: {exc}") from exc
    return _settings
