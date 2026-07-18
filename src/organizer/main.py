"""Entrypoint: load config, initialize the database and run the bot."""

from __future__ import annotations

import logging
import sys

from .bot.app import build_application
from .config import get_settings
from .db.engine import init_db, make_engine, make_session_factory
from .db.repository import EntryRepository
from .embeddings import Embedder
from .llm.classifier import Classifier
from .llm.editor import Editor
from .llm.insights import ReviewAnalyzer
from .llm.search import SearchRanker
from .logging_setup import setup_logging
from .semantic import SemanticIndex


def _build_semantic_index(session_factory, embedder: Embedder) -> None:
    """Create the vec table and embed any entries that aren't indexed yet."""
    logger = logging.getLogger(__name__)
    with session_factory() as session:
        index = SemanticIndex(session, embedder.dim)
        index.ensure_table()
        indexed = index.indexed_ids()
        pending = [e for e in EntryRepository(session).list_all() if e.id not in indexed]
        if pending:
            logger.info("Indexing %s existing entries for semantic memory...", len(pending))
            for entry in pending:
                index.upsert(entry.id, embedder.encode(entry.raw_text))


def main() -> None:
    settings = get_settings()
    setup_logging(settings.log_level)
    logger = logging.getLogger(__name__)

    engine = make_engine(settings.database_url)
    init_db(engine)
    session_factory = make_session_factory(engine)

    if not settings.anthropic_api_key:
        logger.error(
            "ANTHROPIC_API_KEY nao definido no .env — necessario para a Fase 2 "
            "(classificacao). Adicione a chave e rode novamente."
        )
        sys.exit(1)

    classifier = Classifier(api_key=settings.anthropic_api_key)
    embedder = Embedder(settings.embedding_model)
    ranker = SearchRanker(api_key=settings.anthropic_api_key) if settings.search_rerank else None
    analyzer = ReviewAnalyzer(api_key=settings.anthropic_api_key, model=settings.insights_model)
    editor = Editor(api_key=settings.anthropic_api_key)
    _build_semantic_index(session_factory, embedder)

    application = build_application(
        settings, session_factory, classifier, embedder, ranker, analyzer, editor
    )
    logger.info("Starting bot (allowed chat id=%s)", settings.allowed_chat_id)
    application.run_polling()


if __name__ == "__main__":
    main()
