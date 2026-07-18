"""Tests for natural-language editing (Phase 8): parser (mocked) + apply_edit."""

from __future__ import annotations

from datetime import date
from types import SimpleNamespace

from sqlalchemy.orm import Session

from organizer.db.repository import EntryRepository
from organizer.llm.editor import Editor, EntryEdit
from organizer.llm.schema import EntryClassification, EntryType, Priority


class _FakeMessages:
    def __init__(self, result: object) -> None:
        self._result = result
        self.calls: list[dict] = []

    def parse(self, **kwargs):
        self.calls.append(kwargs)
        return SimpleNamespace(parsed_output=self._result)


class _FakeClient:
    def __init__(self, result: object) -> None:
        self.messages = _FakeMessages(result)


# --- parser ----------------------------------------------------------------


def test_edit_builds_content_and_returns_parsed() -> None:
    expected = EntryEdit(priority=Priority.high, fields_to_update=["priority"])
    editor = Editor(api_key="test", client=_FakeClient(expected))

    result = editor.edit("- tipo: task", "marca alta")

    assert result is expected
    sent = editor._client.messages.calls[0]["messages"][0]["content"]
    assert "CURRENT DATE:" in sent
    assert "marca alta" in sent


def test_clean_fields_whitelists_and_dedups() -> None:
    edit = EntryEdit(fields_to_update=["priority", "bogus", "priority", "status"])
    assert edit.clean_fields() == ["priority", "status"]


def test_resolve_and_edit_lists_candidates_and_returns_target() -> None:
    expected = EntryEdit(target_id=3, status="done", fields_to_update=["status"])
    editor = Editor(api_key="test", client=_FakeClient(expected))

    result = editor.resolve_and_edit(
        [(3, "reuniao com Ana"), (5, "relatorio final")],
        "marca a reuniao com a Ana como feita",
    )

    assert result is expected
    assert result.target_id == 3
    sent = editor._client.messages.calls[0]["messages"][0]["content"]
    assert "#3: reuniao com Ana" in sent
    assert "#5: relatorio final" in sent
    assert "candidatas" in sent


# --- apply_edit ------------------------------------------------------------


def _task(session: Session) -> tuple[EntryRepository, int]:
    repo = EntryRepository(session)
    entry = repo.add_raw_entry("revisar o relatorio")
    repo.apply_classification(
        entry,
        EntryClassification(type=EntryType.task, title="Revisar relatorio"),
        "{}",
    )
    return repo, entry.id


def test_apply_edit_changes_fields_and_records_corrections(session: Session) -> None:
    repo, entry_id = _task(session)
    edit = EntryEdit(
        priority=Priority.high,
        due_date=date(2026, 7, 24),
        status="done",
        title="Revisar relatorio final",
        fields_to_update=["priority", "due_date", "status", "title", "unknown"],
    )

    repo.apply_edit(repo.get_by_id(entry_id), edit)

    entry = repo.get_by_id(entry_id)
    assert entry.priority == "high"
    assert entry.due_date.date() == date(2026, 7, 24)
    assert entry.status == "done"
    assert entry.title == "Revisar relatorio final"

    # correctable fields feed the few-shot memory; title/status/unknown do not
    fields = {c.field for c in repo.get_recent_corrections(limit=10)}
    assert {"priority", "due_date"} <= fields
    assert "title" not in fields and "unknown" not in fields


def test_apply_edit_can_clear_a_field(session: Session) -> None:
    repo, entry_id = _task(session)
    repo.apply_edit(
        repo.get_by_id(entry_id),
        EntryEdit(priority=Priority.low, fields_to_update=["priority"]),
    )
    assert repo.get_by_id(entry_id).priority == "low"

    # now clear it (listed in fields_to_update, value null)
    repo.apply_edit(
        repo.get_by_id(entry_id),
        EntryEdit(priority=None, fields_to_update=["priority"]),
    )
    assert repo.get_by_id(entry_id).priority is None
