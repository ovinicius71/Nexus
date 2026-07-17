"""Tests for the Phase 3 query methods."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from sqlalchemy.orm import Session

from organizer.db.repository import EntryRepository


def _task(session, repo, title, due=None, priority=None, status="open"):
    entry = repo.add_raw_entry(title)
    entry.title = title
    entry.type = "task"
    entry.status = status
    entry.due_date = due
    entry.priority = priority
    session.commit()
    session.refresh(entry)
    return entry


def test_open_tasks_ordered_by_due_then_priority(session: Session) -> None:
    repo = EntryRepository(session)
    d18 = datetime(2026, 7, 18, tzinfo=timezone.utc)
    _task(session, repo, "A", due=d18, priority="low")
    _task(session, repo, "B", due=d18, priority="high")
    _task(session, repo, "C", due=None, priority="high")
    _task(session, repo, "D", due=None, priority=None)

    titles = [t.title for t in repo.list_open_tasks()]
    assert titles == ["B", "A", "C", "D"]


def test_open_tasks_excludes_done(session: Session) -> None:
    repo = EntryRepository(session)
    open_task = _task(session, repo, "aberta")
    _task(session, repo, "feita", status="done")

    titles = [t.title for t in repo.list_open_tasks()]
    assert titles == ["aberta"]
    assert open_task.status == "open"


def test_mark_done_removes_from_open(session: Session) -> None:
    repo = EntryRepository(session)
    task = _task(session, repo, "revisar")
    assert len(repo.list_open_tasks()) == 1

    repo.mark_done(task)

    assert task.status == "done"
    assert repo.list_open_tasks() == []


def test_list_today_filters_by_day(session: Session) -> None:
    repo = EntryRepository(session)
    today = repo.add_raw_entry("de hoje")
    old = repo.add_raw_entry("de antes")
    old.created_at = datetime.now(timezone.utc) - timedelta(days=2)
    session.commit()

    titles = [e.raw_text for e in repo.list_today()]
    assert "de hoje" in titles
    assert "de antes" not in titles
    assert today.id is not None


def test_list_by_type(session: Session) -> None:
    repo = EntryRepository(session)
    idea = repo.add_raw_entry("uma ideia")
    idea.type = "idea"
    event = repo.add_raw_entry("um evento")
    event.type = "event"
    session.commit()

    assert [e.raw_text for e in repo.list_by_type("idea")] == ["uma ideia"]
    assert [e.raw_text for e in repo.list_by_type("event")] == ["um evento"]


def test_search_matches_raw_text_and_title_case_insensitive(session: Session) -> None:
    repo = EntryRepository(session)
    e = repo.add_raw_entry("comprar leite no mercado")
    e.title = "Comprar leite"
    session.commit()
    repo.add_raw_entry("reuniao de equipe")

    assert [r.id for r in repo.search("LEITE")] == [e.id]
    assert repo.search("inexistente") == []
