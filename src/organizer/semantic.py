"""Semantic index over entry embeddings, backed by sqlite-vec (Phase 5)."""

from __future__ import annotations

import sqlite_vec
from sqlalchemy import text
from sqlalchemy.orm import Session


class SemanticIndex:
    """Stores and searches entry embeddings in a ``vec0`` virtual table."""

    def __init__(self, session: Session, dim: int) -> None:
        self._session = session
        self._dim = dim

    def ensure_table(self) -> None:
        self._session.execute(
            text(
                f"CREATE VIRTUAL TABLE IF NOT EXISTS vec_entries USING vec0("
                f"entry_id INTEGER PRIMARY KEY, "
                f"embedding FLOAT[{self._dim}] distance_metric=cosine)"
            )
        )
        self._session.commit()

    def indexed_ids(self) -> set[int]:
        rows = self._session.execute(text("SELECT entry_id FROM vec_entries"))
        return {row[0] for row in rows}

    def upsert(self, entry_id: int, vector: list[float]) -> None:
        blob = sqlite_vec.serialize_float32(vector)
        self._session.execute(
            text("DELETE FROM vec_entries WHERE entry_id = :id"), {"id": entry_id}
        )
        self._session.execute(
            text("INSERT INTO vec_entries(entry_id, embedding) VALUES (:id, :vec)"),
            {"id": entry_id, "vec": blob},
        )
        self._session.commit()

    def search(
        self, vector: list[float], k: int = 5, exclude_id: int | None = None
    ) -> list[tuple[int, float]]:
        """Return ``(entry_id, cosine_similarity)`` for the k nearest neighbours."""
        blob = sqlite_vec.serialize_float32(vector)
        limit = k + (1 if exclude_id is not None else 0)
        rows = self._session.execute(
            text(
                "SELECT entry_id, distance FROM vec_entries "
                "WHERE embedding MATCH :vec AND k = :k ORDER BY distance"
            ),
            {"vec": blob, "k": limit},
        )
        results = []
        for entry_id, distance in rows:
            if entry_id == exclude_id:
                continue
            results.append((entry_id, 1.0 - distance))  # cosine distance -> similarity
        return results[:k]
