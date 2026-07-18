"""Q&A over the user's notes (RAG): retrieval is done by the caller; this module
sends the retrieved notes as context to Claude Sonnet and returns a grounded
answer. The answer is free text (not structured), so it uses ``messages.create``.
"""

from __future__ import annotations

import logging
from pathlib import Path

import anthropic

logger = logging.getLogger(__name__)

# Sonnet for synthesis/reasoning over the retrieved notes.
DEFAULT_MODEL = "claude-sonnet-5"

# prompts/qa.md lives at the repo root (src/organizer/llm/qa.py -> parents[3]).
_PROMPT_PATH = Path(__file__).resolve().parents[3] / "prompts" / "qa.md"


def _load_system_prompt() -> str:
    return _PROMPT_PATH.read_text(encoding="utf-8")


def _extract_text(response: object) -> str:
    """Join the text blocks of a Messages API response."""
    parts = []
    for block in getattr(response, "content", []) or []:
        if getattr(block, "type", None) == "text":
            parts.append(block.text)
    return "".join(parts).strip()


class Answerer:
    """Answers a question grounded in the notes passed as context."""

    def __init__(
        self,
        api_key: str,
        model: str = DEFAULT_MODEL,
        client: anthropic.Anthropic | None = None,
    ) -> None:
        self._client = client or anthropic.Anthropic(api_key=api_key)
        self._model = model
        self._system_prompt = _load_system_prompt()

    def answer(self, question: str, context: str) -> str:
        """Return a grounded answer to ``question`` given the notes ``context``."""
        content = f"NOTAS DO USUARIO:\n{context}\n\nPERGUNTA: {question}"
        response = self._client.messages.create(
            model=self._model,
            max_tokens=1024,
            system=self._system_prompt,
            messages=[{"role": "user", "content": content}],
        )
        text = _extract_text(response)
        logger.info("Q&A answered (%s chars)", len(text))
        return text or "Não consegui formular uma resposta."
