"""
Database connection and session handling.

Development runs against local PostgreSQL in Docker, never cloud RDS - a
decision recorded in Chapter 3 and in the Phase 0 handover.

The engine is created lazily. Building it at import time meant that importing
any module in the package required a PostgreSQL driver to be installed and a
URL to be valid, which broke the test suite before it ran a single assertion.
Nothing here touches the database until something actually asks for a session.
"""

from __future__ import annotations

import os
from collections.abc import Iterator

from sqlalchemy import Engine, create_engine, text
from sqlalchemy.orm import Session, sessionmaker

DEFAULT_URL = "postgresql+psycopg://elimu:elimu@localhost:5432/elimu"

_engine: Engine | None = None
_session_factory: sessionmaker[Session] | None = None


def database_url() -> str:
    return os.environ.get("DATABASE_URL", DEFAULT_URL)


def get_engine() -> Engine:
    global _engine
    if _engine is None:
        _engine = create_engine(database_url(), pool_pre_ping=True, future=True)
    return _engine


def get_session_factory() -> sessionmaker[Session]:
    global _session_factory
    if _session_factory is None:
        _session_factory = sessionmaker(
            bind=get_engine(), autoflush=False, expire_on_commit=False
        )
    return _session_factory


def get_session() -> Iterator[Session]:
    """FastAPI dependency."""
    session = get_session_factory()()
    try:
        yield session
    finally:
        session.close()


def ensure_extensions() -> None:
    """pgvector must exist before the curriculum_chunk table can be created."""
    with get_engine().begin() as conn:
        conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))


def healthcheck() -> bool:
    try:
        with get_engine().connect() as conn:
            conn.execute(text("SELECT 1"))
        return True
    except Exception:  # noqa: BLE001 - any failure means "not reachable"
        return False
