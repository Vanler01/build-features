"""SQLite connection handling and forward-only migrations.

Migrations are plain ``.sql`` files in ``migrations/``, applied in filename
order and recorded in ``schema_migrations``. Applying an already-applied
migration is a no-op, so ``migrate()`` is safe to call on every startup.
"""

from __future__ import annotations

import logging
import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

_LOG = logging.getLogger(__name__)

MIGRATIONS_DIR = Path(__file__).parent / "migrations"


def connect(db_path: str | Path) -> sqlite3.Connection:
    """Open a connection with the pragmas this schema assumes.

    ``foreign_keys`` is off by default in SQLite and must be set per
    connection, not per database -- forgetting it silently disables every
    ``ON DELETE CASCADE`` in the schema, which is how account deletion quietly
    stops working.
    """
    conn = sqlite3.connect(str(db_path), isolation_level=None)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")
    conn.execute("PRAGMA busy_timeout = 5000")
    return conn


def migrate(conn: sqlite3.Connection, migrations_dir: Path | None = None) -> list[str]:
    """Apply any migrations not yet recorded. Returns the names applied."""
    directory = migrations_dir or MIGRATIONS_DIR
    conn.execute(
        "CREATE TABLE IF NOT EXISTS schema_migrations ("
        "  name TEXT PRIMARY KEY, applied_at TEXT NOT NULL DEFAULT (datetime('now'))"
        ")"
    )
    applied = {row["name"] for row in conn.execute("SELECT name FROM schema_migrations")}

    newly_applied: list[str] = []
    for path in sorted(directory.glob("*.sql")):
        if path.name in applied:
            continue
        _LOG.info("applying migration %s", path.name)
        # sqlite3.executescript() issues an implicit COMMIT before running, so a
        # Python-side BEGIN around it would be discarded. Transaction control has
        # to be part of the script itself; the script opens the transaction and
        # leaves it open so the bookkeeping INSERT below lands in the same one.
        conn.executescript("BEGIN;\n" + path.read_text())
        try:
            conn.execute("INSERT INTO schema_migrations (name) VALUES (?)", (path.name,))
        except Exception:
            conn.execute("ROLLBACK")
            raise
        conn.execute("COMMIT")
        newly_applied.append(path.name)
    return newly_applied


@contextmanager
def transaction(conn: sqlite3.Connection) -> Iterator[sqlite3.Connection]:
    """Run a block in a transaction, rolling back on any exception.

    The connection is opened with ``isolation_level=None`` (autocommit), so
    transactions are managed explicitly here rather than by sqlite3's implicit
    and surprising default behaviour.
    """
    conn.execute("BEGIN")
    try:
        yield conn
    except Exception:
        conn.execute("ROLLBACK")
        raise
    conn.execute("COMMIT")


def open_database(db_path: str | Path) -> sqlite3.Connection:
    """Connect and bring the schema up to date. The normal entry point."""
    conn = connect(db_path)
    migrate(conn)
    return conn
