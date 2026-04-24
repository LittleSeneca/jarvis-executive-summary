"""Load and validate configuration from environment / .env file."""

import os
from pathlib import Path

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

    # Core
    enabled_plugins: list[str] = Field(default_factory=list)
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
    jarvis_output_file: str | None = None  # explicit output path; defaults to jarvis-brief-YYYY-MM-DD.md

    @field_validator("enabled_plugins", mode="before")
    @classmethod
    def _split_csv(cls, v: object) -> list[str]:
        if isinstance(v, str):
            return [p.strip() for p in v.split(",") if p.strip()]
        return v  # type: ignore[return-value]

    @field_validator("slack_target_type")
    @classmethod
    def _validate_target_type(cls, v: str) -> str:
        if v not in {"user", "channel"}:
            raise ValueError("SLACK_TARGET_TYPE must be 'user' or 'channel'")
        return v

    @model_validator(mode="after")
    def _require_plugins(self) -> "Settings":
        if not self.enabled_plugins:
            raise ConfigError("ENABLED_PLUGINS must list at least one plugin")
        return self


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
