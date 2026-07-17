"""Tests for the SearchRanker (LLM client is mocked — no network)."""

from __future__ import annotations

from types import SimpleNamespace

from organizer.llm.search import Candidate, RankedSearch, SearchRanker


class _FakeMessages:
    def __init__(self, result: object, raises: bool = False) -> None:
        self._result = result
        self._raises = raises
        self.calls: list[dict] = []

    def parse(self, **kwargs):
        self.calls.append(kwargs)
        if self._raises:
            raise RuntimeError("boom")
        return SimpleNamespace(parsed_output=self._result)


class _FakeClient:
    def __init__(self, result: object, raises: bool = False) -> None:
        self.messages = _FakeMessages(result, raises)


def _ranker(result: object, raises: bool = False) -> tuple[SearchRanker, _FakeClient]:
    client = _FakeClient(result, raises)
    return SearchRanker(api_key="test", client=client), client


def _candidates() -> list[Candidate]:
    return [
        Candidate(id=1, text="chamar a Manu para sair", type="task"),
        Candidate(id=2, text="cinema com a Helen", type="event"),
        Candidate(id=3, text="implementar a fase 6 do nexus", type="task"),
    ]


def test_rank_returns_model_ordered_ids() -> None:
    ranker, client = _ranker(RankedSearch(relevant_ids=[2, 1]))

    result = ranker.rank("sair", _candidates())

    assert result == [2, 1]
    sent = client.messages.calls[0]["messages"][0]["content"]
    assert "QUERY: sair" in sent
    assert "cinema com a Helen" in sent


def test_rank_drops_ids_not_offered() -> None:
    # Model hallucinates id 99, which wasn't a candidate: it must be filtered out.
    ranker, _ = _ranker(RankedSearch(relevant_ids=[99, 1]))

    assert ranker.rank("sair", _candidates()) == [1]


def test_rank_empty_candidates_skips_call() -> None:
    ranker, client = _ranker(RankedSearch(relevant_ids=[1]))

    assert ranker.rank("sair", []) == []
    assert client.messages.calls == []


def test_rank_falls_back_to_candidate_order_on_error() -> None:
    ranker, _ = _ranker(None, raises=True)

    assert ranker.rank("sair", _candidates()) == [1, 2, 3]
