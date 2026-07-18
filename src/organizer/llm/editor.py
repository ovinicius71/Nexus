"""Editor: applies a natural-language instruction to an entry via Claude Haiku.

Given an entry's current fields and a free-text instruction ("adia pra sexta e
marca alta"), the model returns the fields to change. Haiku is enough here.
"""

from __future__ import annotations

import logging
from datetime import date
from pathlib import Path

import anthropic
from pydantic import BaseModel, Field

from .schema import EntryType, Priority

logger = logging.getLogger(__name__)

DEFAULT_MODEL = "claude-haiku-4-5"

# Fields the model is allowed to change (guards against unknown attributes).
EDITABLE_FIELDS = ("type", "title", "due_date", "priority", "project", "status")

# prompts/edit.md lives at the repo root (src/organizer/llm/editor.py -> parents[3]).
_PROMPT_PATH = Path(__file__).resolve().parents[3] / "prompts" / "edit.md"


class EntryEdit(BaseModel):
    """Structured edit: the fields to change and their new values.

    ``fields_to_update`` disambiguates "clear this field" (name listed, value
    null) from "leave it untouched" (name absent).
    """

    # Set only in the natural (no-id) flow: which candidate entry to edit.
    target_id: int | None = None
    type: EntryType | None = None
    title: str | None = None
    due_date: date | None = None
    priority: Priority | None = None
    project: str | None = None
    status: str | None = None
    fields_to_update: list[str] = Field(default_factory=list)

    def clean_fields(self) -> list[str]:
        """Requested fields limited to the editable whitelist, de-duplicated."""
        seen: list[str] = []
        for field in self.fields_to_update:
            if field in EDITABLE_FIELDS and field not in seen:
                seen.append(field)
        return seen


def _load_system_prompt() -> str:
    return _PROMPT_PATH.read_text(encoding="utf-8")


class Editor:
    """Turns a free-text instruction into a structured :class:`EntryEdit`."""

    def __init__(
        self,
        api_key: str,
        model: str = DEFAULT_MODEL,
        client: anthropic.Anthropic | None = None,
    ) -> None:
        self._client = client or anthropic.Anthropic(api_key=api_key)
        self._model = model
        self._system_prompt = _load_system_prompt()

    def _parse(self, content: str) -> EntryEdit:
        response = self._client.messages.parse(
            model=self._model,
            max_tokens=512,
            system=self._system_prompt,
            messages=[{"role": "user", "content": content}],
            output_format=EntryEdit,
        )
        result = response.parsed_output
        if result is None:  # refusal or unparsable output
            raise ValueError("Edit returned no structured output")
        return result

    def edit(self, current_state: str, instruction: str) -> EntryEdit:
        """Return the edit implied by ``instruction`` for a known entry (id flow)."""
        content = (
            f"CURRENT DATE: {date.today().isoformat()}\n\n"
            f"Entrada atual:\n{current_state}\n\n"
            f"Instrucao do usuario:\n{instruction}"
        )
        result = self._parse(content)
        logger.info("Edit parsed: fields=%s", result.clean_fields())
        return result

    def resolve_and_edit(
        self, candidates: list[tuple[int, str]], instruction: str
    ) -> EntryEdit:
        """Pick which candidate the instruction refers to and return the edit."""
        lines = [
            f"CURRENT DATE: {date.today().isoformat()}",
            "",
            "Entradas candidatas (escolha em target_id a que a instrucao se refere):",
        ]
        for cid, summary in candidates:
            lines.append(f"#{cid}: {summary}")
        lines += ["", "Instrucao do usuario:", instruction]
        result = self._parse("\n".join(lines))
        logger.info(
            "Edit resolved: target=%s fields=%s", result.target_id, result.clean_fields()
        )
        return result
