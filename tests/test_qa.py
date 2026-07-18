"""Tests for the RAG answerer (Phase 9). The LLM client is mocked — no network."""

from __future__ import annotations

from types import SimpleNamespace

from organizer.llm.qa import Answerer, _extract_text


class _FakeMessages:
    def __init__(self, text: str) -> None:
        self._text = text
        self.calls: list[dict] = []

    def create(self, **kwargs):
        self.calls.append(kwargs)
        return SimpleNamespace(content=[SimpleNamespace(type="text", text=self._text)])


class _FakeClient:
    def __init__(self, text: str) -> None:
        self.messages = _FakeMessages(text)


def test_answer_returns_text_and_sends_context() -> None:
    answerer = Answerer(api_key="test", client=_FakeClient("Você anotou isso em #3."))

    result = answerer.answer("o que pensei sobre o TCC?", "#3 (2026-07-10, idea): tema do TCC")

    assert result == "Você anotou isso em #3."
    sent = answerer._client.messages.calls[0]["messages"][0]["content"]
    assert "PERGUNTA: o que pensei sobre o TCC?" in sent
    assert "tema do TCC" in sent


def test_answer_falls_back_when_empty() -> None:
    answerer = Answerer(api_key="test", client=_FakeClient("   "))
    assert answerer.answer("q", "ctx") == "Não consegui formular uma resposta."


def test_extract_text_joins_text_blocks_only() -> None:
    response = SimpleNamespace(
        content=[
            SimpleNamespace(type="text", text="parte 1 "),
            SimpleNamespace(type="tool_use", text="ignorar"),
            SimpleNamespace(type="text", text="parte 2"),
        ]
    )
    assert _extract_text(response) == "parte 1 parte 2"
