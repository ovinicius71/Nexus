"""Repository layer: isolates data access to ease a future Postgres migration."""

from __future__ import annotations

from datetime import datetime, time, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..llm.classifier import CorrectionExample
from ..llm.schema import EntryClassification
from .models import Correction, Entry, EntryPerson, Person


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
