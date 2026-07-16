"""Shared test fixtures."""

from __future__ import annotations

import pytest
from sqlalchemy.orm import Session

from organizer.db.engine import init_db, make_engine, make_session_factory


@pytest.fixture
def session() -> Session:
    """Provide a session backed by a fresh in-memory SQLite database."""
    engine = make_engine("sqlite:///:memory:")
    init_db(engine)
    factory = make_session_factory(engine)
    with factory() as session:
        yield session
