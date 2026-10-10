"""Engine pragmas that make a single-file SQLite DB usable under concurrency (DATABASE §1).

WAL, foreign_keys=ON, and busy_timeout are not optional polish. Without WAL the
dashboard reads block pipeline writes; without foreign_keys=ON the schema's
referential integrity is decorative; without busy_timeout a write burst surfaces
as SQLITE_BUSY instead of waiting.
"""

from __future__ import annotations

from pathlib import Path

from sqlalchemy import create_engine, event, text
from sqlalchemy.pool import QueuePool


def _engine_for(db_path: Path):
    """Build an engine the same way session.py must, for pragma assertions.

    Kept local to the test so the assertion does not depend on the module
    under test having wired the pragmas — the two are compared after the
    implementation step.
    """
    engine = create_engine(
        f"sqlite:///{db_path}",
        connect_args={"check_same_thread": False, "timeout": 30.0},
        poolclass=QueuePool,
        pool_size=5,
        max_overflow=5,
    )

    @event.listens_for(engine, "connect")
    def _configure(dbapi_conn, _record):  # type: ignore[no-untyped-def]
        cur = dbapi_conn.cursor()
        cur.execute("PRAGMA journal_mode=WAL")
        cur.execute("PRAGMA synchronous=NORMAL")
        cur.execute("PRAGMA foreign_keys=ON")
        cur.execute("PRAGMA busy_timeout=30000")
        cur.close()

    return engine


def test_wal_and_foreign_keys_enabled(tmp_path: Path) -> None:
    """journal_mode=WAL, foreign_keys=1, busy_timeout=30000 (DATABASE §1)."""
    from app.db.session import create_engine_for

    engine = create_engine_for(tmp_path / "t.db")
    try:
        with engine.connect() as conn:
            assert conn.exec_driver_sql("PRAGMA journal_mode").scalar() == "wal"
            assert conn.exec_driver_sql("PRAGMA foreign_keys").scalar() == 1
            assert conn.exec_driver_sql("PRAGMA busy_timeout").scalar() == 30000
    finally:
        engine.dispose()


def test_engine_uses_queuepool_not_pysqlite_default(tmp_path: Path) -> None:
    """QueuePool, not the pysqlite default (DATABASE §1: we control reuse)."""
    from app.db.session import create_engine_for

    engine = create_engine_for(tmp_path / "t.db")
    try:
        assert isinstance(engine.pool, QueuePool)
        assert engine.pool.size() == 5
        assert engine.pool._max_overflow == 5  # noqa: SLF001
    finally:
        engine.dispose()


def test_fk_enforcement_rejects_orphan(tmp_path: Path) -> None:
    """foreign_keys=ON rejects a child row pointing at a missing parent.

    This is the structural property that keeps the schema honest: SQLite
    ignores FK constraints by default, so an orphan insert would silently
    succeed without the pragma.
    """
    import pytest
    from sqlalchemy.exc import IntegrityError

    from app.db.session import create_engine_for

    engine = create_engine_for(tmp_path / "t.db")
    try:
        with engine.begin() as conn:
            conn.execute(text("CREATE TABLE parent (id INTEGER PRIMARY KEY)"))
            conn.execute(
                text(
                    "CREATE TABLE child (id INTEGER PRIMARY KEY,"
                    " parent_id INTEGER NOT NULL REFERENCES parent(id)"
                    " ON DELETE CASCADE)"
                )
            )
        # No parent id=999 exists -> the orphan insert must be rejected.
        with engine.begin() as conn, pytest.raises(IntegrityError):
            conn.execute(text("INSERT INTO child (parent_id) VALUES (999)"))
    finally:
        engine.dispose()
