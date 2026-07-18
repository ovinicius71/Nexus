"""Tests for light habit tracking (Phase A): activity extraction + summary."""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

from sqlalchemy.orm import Session

from organizer.db.repository import EntryRepository
from organizer.export import VaultExporter
from organizer.llm.schema import Activity, EntryClassification, EntryType


def _log(repo: EntryRepository, text: str, activities: list[Activity]):
    entry = repo.add_raw_entry(text)
    repo.apply_classification(
        entry,
        EntryClassification(type=EntryType.note, title=text, activities=activities),
        "{}",
    )
    return entry


def _since_7d() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(days=7)


def test_activities_persisted_and_normalized(session: Session) -> None:
    repo = EntryRepository(session)
    entry = _log(repo, "corri 5km", [Activity(name="Corrida", value=5, unit="KM")])

    stored = repo.get_by_id(entry.id).activities
    assert len(stored) == 1
    a = stored[0]
    assert a.name == "corrida"  # normalized to lowercase
    assert a.value == 5.0
    assert a.unit == "km"
    assert a.occurred_at is not None


def test_activity_without_value(session: Session) -> None:
    repo = EntryRepository(session)
    entry = _log(repo, "fui à academia", [Activity(name="academia")])
    a = repo.get_by_id(entry.id).activities[0]
    assert a.name == "academia"
    assert a.value is None and a.unit is None


def test_activity_summary_aggregates(session: Session) -> None:
    repo = EntryRepository(session)
    _log(repo, "corri 5km", [Activity(name="corrida", value=5, unit="km")])
    _log(repo, "corri 3km", [Activity(name="corrida", value=3, unit="km")])
    _log(repo, "academia", [Activity(name="academia")])

    rows = {r[0]: r for r in repo.activity_summary(_since_7d())}

    assert rows["corrida"][1] == 2  # count
    assert rows["corrida"][2] == 8.0  # summed value
    assert rows["corrida"][3] == "km"  # unit
    assert rows["academia"][1] == 1
    assert rows["academia"][2] is None  # no numeric value


def test_activity_with_explicit_date_is_backdated(session: Session) -> None:
    repo = EntryRepository(session)
    long_ago = date.today() - timedelta(days=20)
    entry = _log(
        repo, "corri 5km", [Activity(name="corrida", value=5, unit="km", occurred_on=long_ago)]
    )

    # occurred_at reflects the stated day, not today
    assert repo.get_by_id(entry.id).activities[0].occurred_at.date() == long_ago
    # and it falls outside the 7-day /habitos window
    assert repo.activity_summary(_since_7d()) == []


def test_reclassification_replaces_activities(session: Session) -> None:
    repo = EntryRepository(session)
    entry = _log(repo, "corri 5km", [Activity(name="corrida", value=5, unit="km")])
    repo.apply_classification(
        repo.get_by_id(entry.id),
        EntryClassification(
            type=EntryType.note, title="x",
            activities=[Activity(name="leitura", value=30, unit="paginas")],
        ),
        "{}",
    )
    assert [a.name for a in repo.get_by_id(entry.id).activities] == ["leitura"]


def test_export_puts_activities_in_frontmatter(session: Session, tmp_path) -> None:
    repo = EntryRepository(session)
    _log(repo, "corri 5km", [Activity(name="corrida", value=5, unit="km")])

    VaultExporter(session, tmp_path).export()

    note = next((tmp_path / "Slipbox").glob("*.md")).read_text(encoding="utf-8")
    assert 'activities: ["corrida 5 km"]' in note
