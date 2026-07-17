"""Search ranker: uses Claude Haiku to pick which candidates match a query.

Local embeddings give cheap recall but weak precision for conceptual queries
(e.g. "sair" should also match "cinema com a Helen"). Haiku reads the candidate
entries and returns only the ones that truly match the query's meaning.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path

import anthropic
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)

# Haiku: cheap and fast, same model family used for classification.
DEFAULT_MODEL = "claude-haiku-4-5"

# prompts/search.md lives at the repo root (src/organizer/llm/search.py -> parents[3]).
_PROMPT_PATH = Path(__file__).resolve().parents[3] / "prompts" / "search.md"


@dataclass
class Candidate:
    """A single entry offered to the ranker."""

    id: int
    text: str
    type: str | None = None


class RankedSearch(BaseModel):
    """Structured ranker output: candidate ids ordered by relevance."""

    relevant_ids: list[int] = Field(default_factory=list)


def _load_system_prompt() -> str:
    return _PROMPT_PATH.read_text(encoding="utf-8")


class SearchRanker:
    """Filters/reorders search candidates by conceptual relevance via Haiku."""

    def __init__(
        self,
        api_key: str,
        model: str = DEFAULT_MODEL,
        client: anthropic.Anthropic | None = None,
    ) -> None:
        self._client = client or anthropic.Anthropic(api_key=api_key)
        self._model = model
        self._system_prompt = _load_system_prompt()

    def _build_user_content(self, query: str, candidates: list[Candidate]) -> str:
        lines = [f"QUERY: {query}", "", "CANDIDATES:"]
        for c in candidates:
            suffix = f" [{c.type}]" if c.type else ""
            lines.append(f"#{c.id}: {c.text}{suffix}")
        return "\n".join(lines)

    def rank(self, query: str, candidates: list[Candidate]) -> list[int]:
        """Return the ids of candidates that match ``query``, most relevant first.

        Never raises: on any API/parse failure it falls back to the candidate
        order it was given, so search keeps working offline-ish (degraded).
        """
        if not candidates:
            return []
        valid_ids = {c.id for c in candidates}
        content = self._build_user_content(query, candidates)
        try:
            response = self._client.messages.parse(
                model=self._model,
                max_tokens=512,
                system=self._system_prompt,
                messages=[{"role": "user", "content": content}],
                output_format=RankedSearch,
            )
            result = response.parsed_output
            if result is None:
                raise ValueError("ranker returned no structured output")
        except Exception:
            logger.exception("Search rerank failed; falling back to candidate order")
            return [c.id for c in candidates]
        # Keep only ids the model was actually given, preserving its order.
        return [i for i in result.relevant_ids if i in valid_ids]
