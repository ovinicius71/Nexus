"""Repository layer: isolates data access to ease a future Postgres migration."""

from __future__ import annotations

from datetime import datetime, time, timedelta, timezone

from sqlalchemy import case, or_, select
from sqlalchemy.orm import Session

from ..llm.classifier import CorrectionExample
from ..llm.schema import EntryClassification
from .models import Connection, Correction, Entry, EntryPerson, Person


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

    # --- Phase 3: queries ----------------------------------------------

    def list_open_tasks(self, limit: int = 50) -> list[Entry]:
        """Open tasks ordered by due date (soonest first, undated last), then priority."""
        stmt = (
            select(Entry)
            .where(Entry.type == "task", Entry.status == "open")
            .order_by(
                Entry.due_date.is_(None),  # dated tasks first
                Entry.due_date.asc(),
                _priority_rank().asc(),
                Entry.created_at.asc(),
            )
            .limit(limit)
        )
        return list(self._session.scalars(stmt))

    def list_today(self, limit: int = 100) -> list[Entry]:
        """Entries created during the current (local) day, oldest first."""
        start, end = _today_bounds()
        stmt = (
            select(Entry)
            .where(Entry.created_at >= start, Entry.created_at < end)
            .order_by(Entry.created_at.asc())
            .limit(limit)
        )
        return list(self._session.scalars(stmt))

    def list_by_type(self, entry_type: str, limit: int = 50) -> list[Entry]:
        """Entries of a given type, newest first."""
        stmt = (
            select(Entry)
            .where(Entry.type == entry_type)
            .order_by(Entry.created_at.desc(), Entry.id.desc())
            .limit(limit)
        )
        return list(self._session.scalars(stmt))

    def search(self, term: str, limit: int = 50) -> list[Entry]:
        """Free-text search over raw text and title (simple LIKE; semantic later)."""
        like = f"%{term}%"
        stmt = (
            select(Entry)
            .where(or_(Entry.raw_text.ilike(like), Entry.title.ilike(like)))
            .order_by(Entry.created_at.desc(), Entry.id.desc())
            .limit(limit)
        )
        return list(self._session.scalars(stmt))

    def list_all(self) -> list[Entry]:
        """All entries, oldest first (used by the Obsidian export)."""
        stmt = select(Entry).order_by(Entry.created_at.asc(), Entry.id.asc())
        return list(self._session.scalars(stmt))

    def get_by_ids(self, ids: list[int]) -> list[Entry]:
        """Fetch entries by id, preserving the order of ``ids``."""
        if not ids:
            return []
        found = {e.id: e for e in self._session.scalars(select(Entry).where(Entry.id.in_(ids)))}
        return [found[i] for i in ids if i in found]

    def mark_done(self, entry: Entry) -> Entry:
        """Mark a task as done."""
        entry.status = "done"
        self._session.commit()
        self._session.refresh(entry)
        return entry

    # --- Phase 5: semantic connections ---------------------------------

    def add_pending_connection(
        self, entry_id: int, related_entry_id: int, similarity: float
    ) -> Connection:
        """Record a suggested connection awaiting the user's accept/reject."""
        connection = Connection(
            entry_id=entry_id, related_entry_id=related_entry_id, similarity=similarity
        )
        self._session.add(connection)
        self._session.commit()
        self._session.refresh(connection)
        return connection

    def get_connection(self, connection_id: int) -> Connection | None:
        return self._session.get(Connection, connection_id)

    def set_connection_accepted(self, connection_id: int, accepted: bool) -> Connection | None:
        """Record the user's feedback on a suggested connection."""
        connection = self._session.get(Connection, connection_id)
        if connection is None:
            return None
        connection.accepted = accepted
        self._session.commit()
        self._session.refresh(connection)
        return connection

    def get_related(self, entry_id: int) -> list[Entry]:
        """Entries linked to ``entry_id`` via an accepted connection (either direction)."""
        stmt = select(Connection).where(
            Connection.accepted.is_(True),
            or_(Connection.entry_id == entry_id, Connection.related_entry_id == entry_id),
        )
        related_ids = []
        for conn in self._session.scalars(stmt):
            other = conn.related_entry_id if conn.entry_id == entry_id else conn.entry_id
            if other not in related_ids:
                related_ids.append(other)
        return self.get_by_ids(sorted(related_ids))

    # --- Phase 2: classification ---------------------------------------

    def apply_classification(
        self, entry: Entry, classification: EntryClassification, llm_json: str
    ) -> Entry:
        """Populate an entry's classification fields and linked people."""
        entry.type = classification.type.value
        entry.title = classification.title
        entry.due_date = _to_datetime(classification.due_date)
        entry.priority = classification.priority.value if classification.priority else None
        entry.project = classification.project
        entry.status = "open" if classification.type.value == "task" else None
        entry.llm_json = llm_json

        self._set_people(entry, classification.people)
        self._session.commit()
        self._session.refresh(entry)
        return entry

    def record_correction(
        self, entry: Entry, field: str, new_value: str | None
    ) -> Correction:
        """Record a user correction and apply it to the entry.

        ``field`` is one of ``type`` / ``priority`` / ``due_date``. Returns the
        stored :class:`Correction` (used later as a few-shot example).
        """
        old_value = _field_as_str(entry, field)
        if field == "due_date":
            entry.due_date = None if new_value is None else _to_datetime(_parse_date(new_value))
        else:
            setattr(entry, field, new_value)
            if field == "type":
                entry.status = "open" if new_value == "task" else None

        correction = Correction(
            entry_id=entry.id, field=field, old_value=old_value, new_value=new_value
        )
        self._session.add(correction)
        self._session.commit()
        self._session.refresh(entry)
        return correction

    def get_recent_corrections(self, limit: int = 10) -> list[CorrectionExample]:
        """Return the most recent corrections as few-shot examples (newest first)."""
        stmt = (
            select(Correction, Entry.raw_text)
            .join(Entry, Correction.entry_id == Entry.id)
            .order_by(Correction.corrected_at.desc(), Correction.id.desc())
            .limit(limit)
        )
        return [
            CorrectionExample(raw_text=raw_text, field=c.field, new_value=c.new_value)
            for c, raw_text in self._session.execute(stmt)
        ]

    def get_people(self, entry: Entry) -> list[str]:
        """Return the names of people linked to an entry."""
        stmt = (
            select(Person.name)
            .join(EntryPerson, EntryPerson.person_id == Person.id)
            .where(EntryPerson.entry_id == entry.id)
            .order_by(Person.name)
        )
        return list(self._session.scalars(stmt))

    def _set_people(self, entry: Entry, names: list[str]) -> None:
        """Replace an entry's linked people with ``names`` (get-or-create)."""
        entry.people.clear()
        seen: set[str] = set()
        for raw_name in names:
            name = raw_name.strip()
            key = name.lower()
            if not name or key in seen:
                continue
            seen.add(key)
            person = self._get_or_create_person(name)
            entry.people.append(EntryPerson(person=person))

    def _get_or_create_person(self, name: str) -> Person:
        person = self._session.scalar(select(Person).where(Person.name == name))
        if person is None:
            person = Person(name=name)
            self._session.add(person)
            self._session.flush()
        return person


def _priority_rank():
    """SQL rank so high < medium < low < null (unset priority sorts last)."""
    return case(
        (Entry.priority == "high", 0),
        (Entry.priority == "medium", 1),
        (Entry.priority == "low", 2),
        else_=3,
    )


def _today_bounds() -> tuple[datetime, datetime]:
    """Return [start, end) of the current local day as naive-UTC datetimes.

    ``created_at`` is stored as UTC wall-clock (SQLite drops tz), so bounds are
    converted to UTC and stripped of tzinfo to compare consistently.
    """
    now_local = datetime.now().astimezone()
    start_local = datetime.combine(now_local.date(), time.min, tzinfo=now_local.tzinfo)
    start_utc = start_local.astimezone(timezone.utc).replace(tzinfo=None)
    return start_utc, start_utc + timedelta(days=1)


def _to_datetime(d) -> datetime | None:
    """Convert a ``date`` to a UTC ``datetime`` at midnight, or pass through None."""
    if d is None:
        return None
    return datetime.combine(d, time.min, tzinfo=timezone.utc)


def _parse_date(value: str):
    from datetime import date as _date

    return _date.fromisoformat(value)


def _field_as_str(entry: Entry, field: str) -> str | None:
    if field == "due_date":
        return entry.due_date.date().isoformat() if entry.due_date else None
    value = getattr(entry, field)
    return None if value is None else str(value)
