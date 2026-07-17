"""Entrypoint: load config, initialize the database and run the bot."""

from __future__ import annotations

import logging
import sys

from .bot.app import build_application
from .config import get_settings
from .db.engine import init_db, make_engine, make_session_factory
from .llm.classifier import Classifier
from .logging_setup import setup_logging


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

    application = build_application(settings, session_factory, classifier)
    logger.info("Starting bot (allowed chat id=%s)", settings.allowed_chat_id)
    application.run_polling()


if __name__ == "__main__":
    main()
