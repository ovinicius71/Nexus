"""Tests for the weekly review: analyzer parser, trigger, snapshot and rendering."""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from types import SimpleNamespace

from sqlalchemy.orm import Session

from organizer.db.repository import EntryRepository
from organizer.llm.insights import ReviewAnalyzer, WeeklyReview
from organizer.llm.schema import EntryClassification, EntryType, Priority
from organizer.review import (
    build_snapshot,
    render_review,
    run_review,
    trigger_met,
    weeks_of_use,
)


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


class _FakeAnalyzer:
    """Stands in for ReviewAnalyzer: returns a fixed review, records the snapshot."""

    def __init__(self, result: WeeklyReview) -> None:
        self._result = result
        self.snapshots: list[str] = []

    def analyze(self, snapshot: str) -> WeeklyReview:
        self.snapshots.append(snapshot)
        return self._result


# --- analyzer parser -------------------------------------------------------


def test_analyze_returns_parsed_output() -> None:
    expected = WeeklyReview(summary="Semana produtiva", growing_themes=["tcc"])
    analyzer = ReviewAnalyzer(api_key="test", client=_FakeClient(expected))

    result = analyzer.analyze("snapshot")

    assert result is expected
    assert result.growing_themes == ["tcc"]


# --- trigger / weeks -------------------------------------------------------


def test_weeks_of_use() -> None:
    now = datetime(2026, 7, 17)
    assert weeks_of_use(None, now) == 0
    assert weeks_of_use(now - timedelta(days=30), now) == 4
    assert weeks_of_use(now - timedelta(days=6), now) == 0


def test_trigger_met() -> None:
    assert trigger_met(200, 0, 200, 4) is True  # entries reached
    assert trigger_met(0, 4, 200, 4) is True  # weeks reached
    assert trigger_met(199, 3, 200, 4) is False  # neither


# --- snapshot --------------------------------------------------------------


def _seed(session: Session) -> EntryRepository:
    repo = EntryRepository(session)
    overdue = repo.add_raw_entry("entregar relatorio")
    repo.apply_classification(
        overdue,
        EntryClassification(
            type=EntryType.task, title="Entregar relatorio",
            due_date=date(2020, 1, 1), priority=Priority.high,
        ),
        "{}",
    )
    idea = repo.add_raw_entry("app de habitos")
    repo.apply_classification(
        idea, EntryClassification(type=EntryType.idea, title="App de habitos"), "{}"
    )
    return repo


def test_build_snapshot_has_all_sections(session: Session) -> None:
    _seed(session)
    snapshot, start, end = build_snapshot(EntryRepository(session))

    assert "VISAO GERAL" in snapshot
    assert "TAREFAS ABERTAS" in snapshot
    assert "[VENCIDA]" in snapshot  # overdue task flagged
    assert "IDEIAS SEM PROJETO" in snapshot
    assert "App de habitos" in snapshot  # orphan idea listed
    assert "ENTRADAS DESTA SEMANA" in snapshot
    assert end - start == timedelta(days=7)


def test_run_review_stores_and_returns(session: Session) -> None:
    _seed(session)
    review_obj = WeeklyReview(summary="ok", postponed_tasks=["Entregar relatorio (vencida)"])
    analyzer = _FakeAnalyzer(review_obj)

    stored, result = run_review(session, analyzer)

    assert result is review_obj
    assert analyzer.snapshots  # the snapshot was actually built and passed
    saved = EntryRepository(session).list_reviews()
    assert len(saved) == 1
    assert saved[0].summary == "ok"
    assert "postponed_tasks" in saved[0].content_json


# --- rendering -------------------------------------------------------------


def test_render_review_skips_empty_sections() -> None:
    review = WeeklyReview(summary="Resumo", growing_themes=["tcc", "estagio"])
    start = datetime(2026, 7, 10)
    end = datetime(2026, 7, 17)

    text = render_review(review, start, end)

    assert "Resumo" in text
    assert "📈 Temas em crescimento" in text
    assert "tcc" in text
    assert "⏳ Tarefas adiadas" not in text  # empty section omitted


def test_render_review_empty_has_fallback() -> None:
    text = render_review(WeeklyReview(), datetime(2026, 7, 10), datetime(2026, 7, 17))
    assert "Sem destaques" in text
