"""Repository layer: isolates data access to ease a future Postgres migration."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from .models import Entry


class EntryRepository:
    """Data-access operations for :class:`Entry`."""

    def __init__(self, session: Session) -> None:
        self._session = session

    def add_raw_entry(self, raw_text: str) -> Entry:
        """Persist a new entry with only the raw text (Phase 1 capture)."""
        entry = Entry(raw_text=raw_text)
        self._session.add(entry)
        self._session.commit()
        self._session.refresh(entry)
        return entry

    def get_by_id(self, entry_id: int) -> Entry | None:
        """Return an entry by id, or ``None`` if it does not exist."""
        return self._session.get(Entry, entry_id)

    def list_recent(self, limit: int = 20) -> list[Entry]:
        """Return the most recent entries, newest first."""
        stmt = select(Entry).order_by(Entry.created_at.desc(), Entry.id.desc()).limit(limit)
        return list(self._session.scalars(stmt))
