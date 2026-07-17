"""Tests for the Phase 2 repository logic: classification, people, corrections."""

from __future__ import annotations

from datetime import date

from sqlalchemy.orm import Session

from organizer.db.repository import EntryRepository
from organizer.llm.schema import EntryClassification, EntryType, Priority


def test_apply_classification_sets_fields_and_people(session: Session) -> None:
    repo = EntryRepository(session)
    entry = repo.add_raw_entry("reuniao com Ana e Bruno sexta")

    classification = EntryClassification(
        type=EntryType.event,
        title="Reuniao com Ana e Bruno",
        due_date=date(2026, 7, 17),
        priority=Priority.medium,
        project="estagio",
        people=["Ana", "Bruno"],
    )
    repo.apply_classification(entry, classification, classification.model_dump_json())

    assert entry.type == "event"
    assert entry.title == "Reuniao com Ana e Bruno"
    assert entry.due_date.date() == date(2026, 7, 17)
    assert entry.priority == "medium"
    assert entry.project == "estagio"
    assert entry.status is None  # only tasks get a status
    assert repo.get_people(entry) == ["Ana", "Bruno"]


def test_task_classification_gets_open_status(session: Session) -> None:
    repo = EntryRepository(session)
    entry = repo.add_raw_entry("comprar leite")
    classification = EntryClassification(type=EntryType.task, title="Comprar leite")
    repo.apply_classification(entry, classification, "{}")
    assert entry.status == "open"


def test_people_are_deduplicated_and_reused(session: Session) -> None:
    repo = EntryRepository(session)
    e1 = repo.add_raw_entry("cafe com Ana")
    repo.apply_classification(
        e1, EntryClassification(type=EntryType.event, title="Cafe", people=["Ana", "ana"]), "{}"
    )
    e2 = repo.add_raw_entry("ligar para Ana")
    repo.apply_classification(
        e2, EntryClassification(type=EntryType.task, title="Ligar", people=["Ana"]), "{}"
    )

    from organizer.db.models import Person

    assert session.query(Person).count() == 1  # single shared Person row
    assert repo.get_people(e1) == ["Ana"]


def test_record_correction_updates_entry_and_stores_history(session: Session) -> None:
    repo = EntryRepository(session)
    entry = repo.add_raw_entry("revisar capitulo do tcc")
    repo.apply_classification(
        entry, EntryClassification(type=EntryType.note, title="Revisar capitulo"), "{}"
    )

    repo.record_correction(entry, "type", "task")

    assert entry.type == "task"
    assert entry.status == "open"  # became a task
    examples = repo.get_recent_corrections()
    assert len(examples) == 1
    assert examples[0].field == "type"
    assert examples[0].new_value == "task"
    assert examples[0].raw_text == "revisar capitulo do tcc"


def test_clear_due_date_correction(session: Session) -> None:
    repo = EntryRepository(session)
    entry = repo.add_raw_entry("anotar ideia aleatoria")
    repo.apply_classification(
        entry,
        EntryClassification(type=EntryType.idea, title="Ideia", due_date=date(2026, 1, 1)),
        "{}",
    )
    assert entry.due_date is not None

    repo.record_correction(entry, "due_date", None)

    assert entry.due_date is None
    examples = repo.get_recent_corrections()
    assert examples[0].field == "due_date"
    assert examples[0].new_value is None


def test_recent_corrections_newest_first(session: Session) -> None:
    repo = EntryRepository(session)
    entry = repo.add_raw_entry("algo")
    repo.apply_classification(entry, EntryClassification(type=EntryType.note, title="x"), "{}")

    repo.record_correction(entry, "type", "task")
    repo.record_correction(entry, "priority", "high")

    fields = [c.field for c in repo.get_recent_corrections()]
    assert fields == ["priority", "type"]
