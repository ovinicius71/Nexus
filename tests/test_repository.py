"""Tests for the repository layer (Phase 1: raw capture)."""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy.orm import Session

from organizer.db.repository import EntryRepository


def test_add_raw_entry_persists_text_and_timestamp(session: Session) -> None:
    repo = EntryRepository(session)

    before = datetime.now(timezone.utc)
    entry = repo.add_raw_entry("comprar leite amanhã")
    after = datetime.now(timezone.utc)

    assert entry.id is not None
    assert entry.raw_text == "comprar leite amanhã"
    # created_at is set automatically, within the call window.
    created = entry.created_at
    if created.tzinfo is None:
        created = created.replace(tzinfo=timezone.utc)
    assert before <= created <= after
    # Classification fields stay null in Phase 1.
    assert entry.type is None
    assert entry.due_date is None
    assert entry.priority is None


def test_ids_are_incremental(session: Session) -> None:
    repo = EntryRepository(session)

    first = repo.add_raw_entry("primeira")
    second = repo.add_raw_entry("segunda")

    assert second.id > first.id


def test_get_by_id(session: Session) -> None:
    repo = EntryRepository(session)
    entry = repo.add_raw_entry("uma ideia")

    fetched = repo.get_by_id(entry.id)
    assert fetched is not None
    assert fetched.id == entry.id
    assert fetched.raw_text == "uma ideia"

    assert repo.get_by_id(999_999) is None


def test_list_recent_newest_first(session: Session) -> None:
    repo = EntryRepository(session)
    repo.add_raw_entry("a")
    repo.add_raw_entry("b")
    repo.add_raw_entry("c")

    recent = repo.list_recent(limit=2)
    assert len(recent) == 2
    assert [e.raw_text for e in recent] == ["c", "b"]
