"""Tests for the Classifier (LLM client is mocked — no network)."""

from __future__ import annotations

from datetime import date
from types import SimpleNamespace

from organizer.llm.classifier import Classifier, CorrectionExample
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


def _make_classifier(result: object) -> tuple[Classifier, _FakeClient]:
    client = _FakeClient(result)
    return Classifier(api_key="test", client=client), client


def test_classify_returns_parsed_output() -> None:
    expected = EntryClassification(
        type=EntryType.task, title="Comprar leite", due_date=date(2026, 7, 17)
    )
    classifier, _ = _make_classifier(expected)

    result = classifier.classify("comprar leite amanha")

    assert result is expected
    assert result.type is EntryType.task
    assert result.priority is None


def test_build_user_content_includes_date_and_text() -> None:
    classifier, client = _make_classifier(
        EntryClassification(type=EntryType.note, title="x")
    )
    classifier.classify("uma nota qualquer")

    sent = client.messages.calls[0]["messages"][0]["content"]
    assert "CURRENT DATE:" in sent
    assert "uma nota qualquer" in sent


def test_corrections_are_injected_as_few_shot() -> None:
    classifier, client = _make_classifier(
        EntryClassification(type=EntryType.task, title="x", priority=Priority.high)
    )
    corrections = [
        CorrectionExample(raw_text="comprar leite", field="type", new_value="task"),
        CorrectionExample(raw_text="revisar tcc", field="priority", new_value=None),
    ]
    classifier.classify("comprar pao", corrections=corrections)

    sent = client.messages.calls[0]["messages"][0]["content"]
    assert "Recent user corrections" in sent
    assert "comprar leite" in sent
    assert "correct type: task" in sent
    assert "correct priority: null" in sent
