"""Tests for the semantic index (sqlite-vec) and connection feedback (Phase 5)."""

from __future__ import annotations

from sqlalchemy.orm import Session

from organizer.db.repository import EntryRepository
from organizer.semantic import SemanticIndex


def _index(session: Session) -> SemanticIndex:
    index = SemanticIndex(session, dim=4)
    index.ensure_table()
    return index


def test_search_returns_nearest_first(session: Session) -> None:
    index = _index(session)
    index.upsert(1, [1, 0, 0, 0])
    index.upsert(2, [0, 1, 0, 0])
    index.upsert(3, [0.8, 0.2, 0, 0])

    results = index.search([1, 0, 0, 0], k=2)
    ids = [r[0] for r in results]
    assert ids[0] == 1
    assert 3 in ids
    assert results[0][1] > 0.99  # cosine similarity ~ 1


def test_search_excludes_self(session: Session) -> None:
    index = _index(session)
    index.upsert(1, [1, 0, 0, 0])
    index.upsert(2, [0.9, 0.1, 0, 0])

    results = index.search([1, 0, 0, 0], k=1, exclude_id=1)
    assert [r[0] for r in results] == [2]


def test_upsert_replaces_existing_vector(session: Session) -> None:
    index = _index(session)
    index.upsert(1, [1, 0, 0, 0])
    index.upsert(1, [0, 1, 0, 0])

    assert index.indexed_ids() == {1}
    results = index.search([0, 1, 0, 0], k=1)
    assert results[0][0] == 1 and results[0][1] > 0.99


def test_connection_feedback_and_related(session: Session) -> None:
    repo = EntryRepository(session)
    a = repo.add_raw_entry("ideia a")
    b = repo.add_raw_entry("ideia b")

    conn = repo.add_pending_connection(a.id, b.id, 0.82)
    assert conn.accepted is None

    repo.set_connection_accepted(conn.id, True)
    assert repo.get_connection(conn.id).accepted is True
    # related works in both directions
    assert [e.id for e in repo.get_related(a.id)] == [b.id]
    assert [e.id for e in repo.get_related(b.id)] == [a.id]


def test_rejected_connection_is_not_related(session: Session) -> None:
    repo = EntryRepository(session)
    a = repo.add_raw_entry("a")
    b = repo.add_raw_entry("b")
    conn = repo.add_pending_connection(a.id, b.id, 0.7)
    repo.set_connection_accepted(conn.id, False)

    assert repo.get_related(a.id) == []
