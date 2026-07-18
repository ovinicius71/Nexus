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


class Activity(BaseModel):
    """A measurable/repeatable activity mentioned in a note ("corri 5km")."""

    name: str  # normalized activity name, e.g. "corrida", "academia", "leitura"
    value: float | None = None  # numeric amount if stated, else null
    unit: str | None = None  # e.g. "km", "h", "paginas"; null if not stated
    occurred_on: date | None = None  # when it happened (ISO), if stated; else null → entry's date


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
    activities: list[Activity] = Field(default_factory=list)
