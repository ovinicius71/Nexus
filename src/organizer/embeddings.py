"""Local text embeddings via sentence-transformers (Phase 5).

The model runs offline (no API cost). It is loaded lazily on first use so
importing this module — and running the tests — stays cheap.
"""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)


class Embedder:
    """Wraps a sentence-transformers model, loaded on first use."""

    def __init__(self, model_name: str) -> None:
        self._model_name = model_name
        self._model = None

    def _load(self):
        if self._model is None:
            from sentence_transformers import SentenceTransformer

            logger.info("Loading embedding model %s (first run downloads it)", self._model_name)
            self._model = SentenceTransformer(self._model_name)
        return self._model

    @property
    def dim(self) -> int:
        model = self._load()
        # sentence-transformers renamed this method; support both.
        getter = getattr(model, "get_embedding_dimension", None) or \
            model.get_sentence_embedding_dimension
        return getter()

    def encode(self, text: str) -> list[float]:
        """Return a normalized embedding (unit vector, for cosine similarity)."""
        vector = self._load().encode(text, normalize_embeddings=True)
        return vector.astype("float32").tolist()
