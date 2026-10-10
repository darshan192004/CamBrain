"""SQLite engine, session factory, and connect-time pragmas (DATABASE §1).

WAL lets the API read while a pipeline writes — the difference between a
responsive dashboard and one that blocks during an event burst. foreign_keys=ON
is mandatory: SQLite disables FK enforcement by default, which would leave the
schema's referential integrity decorative.
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

from sqlalchemy import create_engine, event
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import QueuePool

from app.core.config import settings


def create_engine_for(db_path: Path | str) -> Engine:
    """Build a SQLite engine wired with the pragmas the schema depends on.

    Args:
        db_path: Filesystem path to the `.db` file (parent must be writable).

    Returns:
        An engine using QueuePool (not the pysqlite default) so connection
        reuse is explicit and bounded.
    """
    engine = create_engine(
        f"sqlite:///{db_path}",
        connect_args={"check_same_thread": False, "timeout": 30.0},
        poolclass=QueuePool,
        pool_size=5,
        max_overflow=5,
    )

    @event.listens_for(engine, "connect")
    def _configure(dbapi_conn, _record) -> None:  # type: ignore[no-untyped-def]
        cur = dbapi_conn.cursor()
        cur.execute("PRAGMA journal_mode=WAL")
        cur.execute("PRAGMA synchronous=NORMAL")
        cur.execute("PRAGMA foreign_keys=ON")
        cur.execute("PRAGMA busy_timeout=30000")
        cur.close()

    return engine


engine = create_engine_for(settings.db_path)
SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


def get_session() -> Iterator[Session]:
    """Yield a request-scoped session, closing it on exit."""
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()
