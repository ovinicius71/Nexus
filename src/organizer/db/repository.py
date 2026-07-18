"""Repository layer: isolates data access to ease a future Postgres migration."""

from __future__ import annotations

from datetime import date, datetime, time, timedelta, timezone

from sqlalchemy import case, func, or_, select
from sqlalchemy.orm import Session

from ..llm.classifier import CorrectionExample
from ..llm.schema import EntryClassification
from .models import (
    Activity,
    AppSetting,
    Connection,
    Correction,
    Entry,
    EntryPerson,
    Person,
    Review,
)


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

    def list_due_today_or_overdue(self, today: date, limit: int = 100) -> list[Entry]:
        """Open tasks due today or already overdue, soonest first (the day's to-do).

        Due dates are stored at midnight of their calendar date, so a task is
        "for today" if its due date is before tomorrow.
        """
        end = datetime.combine(today + timedelta(days=1), time.min)
        stmt = (
            select(Entry)
            .where(
                Entry.type == "task",
                Entry.status == "open",
                Entry.due_date.is_not(None),
                Entry.due_date < end,
            )
            .order_by(Entry.due_date.asc(), _priority_rank().asc(), Entry.id.asc())
            .limit(limit)
        )
        return list(self._session.scalars(stmt))

    def list_events_on_day(self, today: date, limit: int = 100) -> list[Entry]:
        """Events whose date falls on ``today``, earliest first."""
        start = datetime.combine(today, time.min)
        end = start + timedelta(days=1)
        stmt = (
            select(Entry)
            .where(
                Entry.type == "event",
                Entry.due_date.is_not(None),
                Entry.due_date >= start,
                Entry.due_date < end,
            )
            .order_by(Entry.due_date.asc(), Entry.id.asc())
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

    def list_connection_feedback(self) -> list[tuple[float, bool]]:
        """Decided connections as ``(similarity, accepted)`` pairs (for calibration)."""
        stmt = select(Connection.similarity, Connection.accepted).where(
            Connection.accepted.is_not(None)
        )
        return [(sim, bool(acc)) for sim, acc in self._session.execute(stmt)]

    def get_setting(self, key: str) -> str | None:
        """Return a stored app setting value, or ``None`` if unset."""
        row = self._session.get(AppSetting, key)
        return row.value if row is not None else None

    def set_setting(self, key: str, value: str) -> None:
        """Insert or update an app setting."""
        row = self._session.get(AppSetting, key)
        if row is None:
            self._session.add(AppSetting(key=key, value=value))
        else:
            row.value = value
        self._session.commit()

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

    # --- Phase 6: insights / weekly review -----------------------------

    def count_entries(self) -> int:
        """Total number of entries (used by the proactivity trigger)."""
        return self._session.scalar(select(func.count(Entry.id))) or 0

    def first_entry_at(self) -> datetime | None:
        """Timestamp of the oldest entry, or ``None`` if the base is empty."""
        return self._session.scalar(select(func.min(Entry.created_at)))

    def list_since(self, since: datetime) -> list[Entry]:
        """Entries created at or after ``since`` (naive UTC), oldest first."""
        stmt = (
            select(Entry)
            .where(Entry.created_at >= since)
            .order_by(Entry.created_at.asc(), Entry.id.asc())
        )
        return list(self._session.scalars(stmt))

    def add_review(
        self,
        period_start: datetime,
        period_end: datetime,
        summary: str,
        content_json: str,
    ) -> Review:
        """Persist a generated weekly review."""
        review = Review(
            period_start=period_start,
            period_end=period_end,
            summary=summary,
            content_json=content_json,
        )
        self._session.add(review)
        self._session.commit()
        self._session.refresh(review)
        return review

    def list_reviews(self, limit: int = 50) -> list[Review]:
        """Stored reviews, newest first."""
        stmt = select(Review).order_by(Review.created_at.desc(), Review.id.desc()).limit(limit)
        return list(self._session.scalars(stmt))

    # --- Phase A: activities / light habit tracking --------------------

    def list_recent_activities(self, limit: int = 50) -> list[Activity]:
        """Logged activities, most recent first."""
        stmt = (
            select(Activity)
            .order_by(Activity.occurred_at.desc(), Activity.id.desc())
            .limit(limit)
        )
        return list(self._session.scalars(stmt))

    def activity_summary(
        self, since: datetime
    ) -> list[tuple[str, int, float | None, str | None]]:
        """Aggregate activities since ``since`` as ``(name, count, total, unit)``.

        Ordered by frequency (most done first). ``total`` sums the numeric values
        (``None`` when no value was recorded); ``unit`` is a representative unit.
        """
        stmt = (
            select(
                Activity.name,
                func.count(Activity.id),
                func.sum(Activity.value),
                func.max(Activity.unit),
            )
            .where(Activity.occurred_at >= since)
            .group_by(Activity.name)
            .order_by(func.count(Activity.id).desc(), Activity.name.asc())
        )
        return [
            (name, int(count), total, unit)
            for name, count, total, unit in self._session.execute(stmt)
        ]

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
        self._set_activities(entry, classification.activities)
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

    def apply_edit(self, entry: Entry, edit) -> Entry:
        """Apply a natural-language :class:`EntryEdit` to an entry.

        Changes to ``type`` / ``priority`` / ``due_date`` also go through
        :meth:`record_correction`, so they feed the classifier's few-shot memory.
        """
        for field in edit.clean_fields():
            value = getattr(edit, field)
            if field == "type":
                self.record_correction(entry, "type", value.value if value else None)
            elif field == "priority":
                self.record_correction(entry, "priority", value.value if value else None)
            elif field == "due_date":
                self.record_correction(entry, "due_date", value.isoformat() if value else None)
            elif field == "title":
                entry.title = value
            elif field == "project":
                entry.project = value
            elif field == "status":
                entry.status = value
        self._session.commit()
        self._session.refresh(entry)
        return entry

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

    def _set_activities(self, entry: Entry, activities: list) -> None:
        """Replace an entry's logged activities with the classified ones.

        ``occurred_at`` uses the activity's own date when the note stated one
        (e.g. "ontem corri"); otherwise it falls back to the entry's timestamp.
        """
        entry.activities.clear()
        for a in activities:
            name = (a.name or "").strip().lower()
            if not name:
                continue
            unit = a.unit.strip().lower() if a.unit else None
            occurred_at = (
                datetime.combine(a.occurred_on, time.min)
                if getattr(a, "occurred_on", None) is not None
                else entry.created_at
            )
            entry.activities.append(
                Activity(name=name, value=a.value, unit=unit, occurred_at=occurred_at)
            )

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
