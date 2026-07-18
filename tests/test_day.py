"""Tests for the 'day' queries (Phase 7): tasks due today/overdue + today's events."""

from __future__ import annotations

from datetime import date, timedelta

from sqlalchemy.orm import Session

from organizer.db.repository import EntryRepository
from organizer.llm.schema import EntryClassification, EntryType


def _task(repo: EntryRepository, text: str, due: date | None):
    entry = repo.add_raw_entry(text)
    repo.apply_classification(
        entry, EntryClassification(type=EntryType.task, title=text, due_date=due), "{}"
    )
    return entry


def _event(repo: EntryRepository, text: str, due: date | None):
    entry = repo.add_raw_entry(text)
    repo.apply_classification(
        entry, EntryClassification(type=EntryType.event, title=text, due_date=due), "{}"
    )
    return entry


def test_due_today_or_overdue(session: Session) -> None:
    repo = EntryRepository(session)
    today = date.today()
    overdue = _task(repo, "atrasada", today - timedelta(days=2))
    due_today = _task(repo, "de hoje", today)
    _task(repo, "amanha", today + timedelta(days=1))  # future: excluded
    _task(repo, "sem prazo", None)  # undated: excluded
    done = _task(repo, "feita atrasada", today - timedelta(days=1))
    repo.mark_done(done)  # done: excluded

    result = repo.list_due_today_or_overdue(today)

    # overdue comes first (earlier due date), then today's; nothing else
    assert [e.id for e in result] == [overdue.id, due_today.id]


def test_events_on_day(session: Session) -> None:
    repo = EntryRepository(session)
    today = date.today()
    today_event = _event(repo, "reuniao hoje", today)
    _event(repo, "evento amanha", today + timedelta(days=1))  # excluded
    _event(repo, "evento sem data", None)  # excluded

    result = repo.list_events_on_day(today)

    assert [e.id for e in result] == [today_event.id]
