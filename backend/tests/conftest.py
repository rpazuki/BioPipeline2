"""Shared test fixtures.

Database tests run against a real PostgreSQL, never SQLite: the schema depends
on ``FOR UPDATE SKIP LOCKED``, JSONB, partial indexes, ``num_nonnulls``, and
plpgsql triggers, so a SQLite path would silently diverge (document 12).
"""

from __future__ import annotations

import os
from collections.abc import Iterator

import pytest
from sqlalchemy import Engine, create_engine, text
from sqlalchemy.orm import Session, sessionmaker

TEST_DATABASE_URL = os.environ.get(
    "BP_TEST_DATABASE_URL",
    "postgresql+psycopg://biopipeline:biopipeline@localhost:55432/biopipeline2",
)


@pytest.fixture(scope="session")
def engine() -> Iterator[Engine]:
    engine = create_engine(TEST_DATABASE_URL, future=True)
    try:
        with engine.connect() as connection:
            connection.execute(text("SELECT 1"))
    except Exception as exc:  # pragma: no cover - environment guard
        pytest.skip(f"PostgreSQL not reachable at {TEST_DATABASE_URL}: {exc}")
    yield engine
    engine.dispose()


@pytest.fixture
def db(engine: Engine) -> Iterator[Session]:
    """A session in a transaction that is always rolled back.

    Tests never see each other's rows and the database is never left dirty.
    """
    connection = engine.connect()
    transaction = connection.begin()
    session = sessionmaker(bind=connection, expire_on_commit=False)()
    try:
        yield session
    finally:
        session.close()
        transaction.rollback()
        connection.close()
