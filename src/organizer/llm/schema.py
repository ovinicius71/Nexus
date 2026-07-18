"""Pydantic schema for the structured classification output."""

from __future__ import annotations

from datetime import date
from enum import Enum

from pydantic import BaseModel, Field


class EntryType(str, Enum):
    idea = "idea"
    task = "task"
    event = "event"
    note = "note"
    happening = "happening"  # personal, emotional occurrence ("acontecimento")


class Priority(str, Enum):
    high = "high"
    medium = "medium"
    low = "low"


class EntryClassification(BaseModel):
    """Structured result of classifying one raw note.

    Fields that cannot be inferred from the text stay ``None`` / empty — the
    model is instructed never to invent a due date or priority.
    """

    type: EntryType
    title: str
    due_date: date | None = None
    priority: Priority | None = None
    project: str | None = None
    people: list[str] = Field(default_factory=list)
