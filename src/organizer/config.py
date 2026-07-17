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
    vault_path: str = "vault"
    # Phase 5: local semantic memory
    embedding_model: str = "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"
    # Above this, a new entry suggests a connection.
    similarity_threshold: float = 0.6
    # Below this, a semantic "related" result in /buscar is dropped as irrelevant.
    search_threshold: float = 0.45
    # When true, /buscar sends candidates to Claude Haiku to filter by meaning
    # (e.g. "sair" also matches "cinema com a Helen"). Needs ANTHROPIC_API_KEY.
    search_rerank: bool = True
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
