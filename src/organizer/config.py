"""Application configuration loaded from environment / .env file."""

from __future__ import annotations

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Runtime settings.

    Values are read from environment variables or a local ``.env`` file.
    Field names map to upper-case env vars (e.g. ``telegram_bot_token`` ->
    ``TELEGRAM_BOT_TOKEN``).
    """

    telegram_bot_token: str
    # Reserved for Phase 2 (LLM classification); not used yet.
    anthropic_api_key: str | None = None
    allowed_chat_id: int
    database_url: str = "sqlite:///organizer.db"
    log_level: str = "INFO"

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )


@lru_cache
def get_settings() -> Settings:
    """Return a cached ``Settings`` instance."""
    return Settings()  # type: ignore[call-arg]
