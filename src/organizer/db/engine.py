"""Engine and session factory."""

from __future__ import annotations

from sqlalchemy import Engine, create_engine
from sqlalchemy.orm import Session, sessionmaker

from .models import Base


def make_engine(database_url: str) -> Engine:
    """Create a SQLAlchemy engine for the given URL."""
    connect_args = {}
    if database_url.startswith("sqlite"):
        # Allow usage across the bot's async handler threads.
        connect_args["check_same_thread"] = False
    return create_engine(database_url, connect_args=connect_args, future=True)


def make_session_factory(engine: Engine) -> sessionmaker[Session]:
    """Create a configured session factory bound to ``engine``."""
    return sessionmaker(bind=engine, expire_on_commit=False, future=True)


def init_db(engine: Engine) -> None:
    """Create all tables if they do not exist."""
    Base.metadata.create_all(engine)
