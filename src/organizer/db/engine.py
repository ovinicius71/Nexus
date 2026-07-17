"""Engine and session factory."""

from __future__ import annotations

import sqlite_vec
from sqlalchemy import Engine, create_engine, event
from sqlalchemy.orm import Session, sessionmaker

from .models import Base


def make_engine(database_url: str) -> Engine:
    """Create a SQLAlchemy engine for the given URL.

    For SQLite, the sqlite-vec extension is loaded on every new connection so
    the ``vec0`` virtual table (semantic memory, Phase 5) is available.
    """
    connect_args = {}
    if database_url.startswith("sqlite"):
        # Allow usage across the bot's async handler threads.
        connect_args["check_same_thread"] = False
    engine = create_engine(database_url, connect_args=connect_args, future=True)

    if database_url.startswith("sqlite"):
        @event.listens_for(engine, "connect")
        def _load_sqlite_vec(dbapi_conn, _record):  # pragma: no cover - driver hook
            dbapi_conn.enable_load_extension(True)
            sqlite_vec.load(dbapi_conn)
            dbapi_conn.enable_load_extension(False)

    return engine


def make_session_factory(engine: Engine) -> sessionmaker[Session]:
    """Create a configured session factory bound to ``engine``."""
    return sessionmaker(bind=engine, expire_on_commit=False, future=True)


def init_db(engine: Engine) -> None:
    """Create all tables if they do not exist."""
    Base.metadata.create_all(engine)
