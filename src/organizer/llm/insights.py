"""Weekly review analyzer: turns a data snapshot into insights via Claude Sonnet.

Sonnet is used here (not Haiku) because the weekly review is an analytical task
over aggregated history, run at most once a week, so the extra cost is justified.
"""

from __future__ import annotations

import logging
from pathlib import Path

import anthropic
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)

# Sonnet for analysis/insights (per project decision).
DEFAULT_MODEL = "claude-sonnet-5"

# prompts/review.md lives at the repo root (src/organizer/llm/insights.py -> parents[3]).
_PROMPT_PATH = Path(__file__).resolve().parents[3] / "prompts" / "review.md"


class WeeklyReview(BaseModel):
    """Structured weekly review returned by the model."""

    summary: str = ""
    postponed_tasks: list[str] = Field(default_factory=list)
    growing_themes: list[str] = Field(default_factory=list)
    orphan_ideas: list[str] = Field(default_factory=list)
    routine_patterns: list[str] = Field(default_factory=list)


def _load_system_prompt() -> str:
    return _PROMPT_PATH.read_text(encoding="utf-8")


class ReviewAnalyzer:
    """Generates a :class:`WeeklyReview` from a text snapshot of the database."""

    def __init__(
        self,
        api_key: str,
        model: str = DEFAULT_MODEL,
        client: anthropic.Anthropic | None = None,
    ) -> None:
        self._client = client or anthropic.Anthropic(api_key=api_key)
        self._model = model
        self._system_prompt = _load_system_prompt()

    def analyze(self, snapshot: str) -> WeeklyReview:
        """Analyze ``snapshot`` and return structured insights. Raises on failure."""
        response = self._client.messages.parse(
            model=self._model,
            max_tokens=2048,
            system=self._system_prompt,
            messages=[{"role": "user", "content": snapshot}],
            output_format=WeeklyReview,
        )
        result = response.parsed_output
        if result is None:  # refusal or unparsable output
            raise ValueError("Review returned no structured output")
        logger.info("Weekly review generated")
        return result
