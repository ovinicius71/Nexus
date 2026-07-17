"""Classifier: turns a raw note into structured fields via Claude Haiku."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import date
from pathlib import Path

import anthropic

from .schema import EntryClassification

logger = logging.getLogger(__name__)

# Haiku for cheap, fast classification (per project decision). Structured
# outputs are supported on Haiku 4.5; do NOT pass thinking/effort (unsupported).
DEFAULT_MODEL = "claude-haiku-4-5"

# prompts/classify.md lives at the repo root: src/organizer/llm/classifier.py
# -> parents[3] is the repo root.
_PROMPT_PATH = Path(__file__).resolve().parents[3] / "prompts" / "classify.md"


@dataclass
class CorrectionExample:
    """A past user correction, used as a few-shot example."""

    raw_text: str
    field: str
    new_value: str | None


def _load_system_prompt() -> str:
    return _PROMPT_PATH.read_text(encoding="utf-8")


class Classifier:
    """Classifies raw notes into :class:`EntryClassification`."""

    def __init__(
        self,
        api_key: str,
        model: str = DEFAULT_MODEL,
        client: anthropic.Anthropic | None = None,
    ) -> None:
        self._client = client or anthropic.Anthropic(api_key=api_key)
        self._model = model
        self._system_prompt = _load_system_prompt()

    def _build_user_content(
        self, raw_text: str, corrections: list[CorrectionExample] | None
    ) -> str:
        parts = [f"CURRENT DATE: {date.today().isoformat()}"]
        if corrections:
            lines = ["", "Recent user corrections — respect these patterns:"]
            for c in corrections:
                value = "null" if c.new_value is None else c.new_value
                lines.append(f'- Note "{c.raw_text}" → correct {c.field}: {value}')
            parts.append("\n".join(lines))
        parts.append("\nNote to classify:\n" + raw_text)
        return "\n".join(parts)

    def classify(
        self,
        raw_text: str,
        corrections: list[CorrectionExample] | None = None,
    ) -> EntryClassification:
        """Classify ``raw_text``. Raises on API failure (SDK retries first)."""
        content = self._build_user_content(raw_text, corrections)
        response = self._client.messages.parse(
            model=self._model,
            max_tokens=1024,
            system=self._system_prompt,
            messages=[{"role": "user", "content": content}],
            output_format=EntryClassification,
        )
        result = response.parsed_output
        if result is None:  # refusal or unparsable output
            raise ValueError("Classification returned no structured output")
        logger.info("Classified note as type=%s", result.type.value)
        return result
