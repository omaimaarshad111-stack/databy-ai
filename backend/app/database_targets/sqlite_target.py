from contextlib import closing
from pathlib import Path
import sqlite3

from sqlalchemy import create_engine, event
from sqlalchemy.engine import Engine
from sqlalchemy.pool import QueuePool

from app.core.config import get_settings
from app.database_targets.exceptions import InvalidDatabaseFileError

SQLITE_HEADER = b"SQLite format 3\x00"


def validate_sqlite_file(path: Path) -> None:
    try:
        with path.open("rb") as database_file:
            header = database_file.read(100)
    except OSError:
        raise InvalidDatabaseFileError("The uploaded file could not be read.") from None

    if len(header) < 100 or not header.startswith(SQLITE_HEADER):
        raise InvalidDatabaseFileError("The uploaded file is not a valid SQLite database.")

    if header[18:20] == b"\x02\x02":
        raise InvalidDatabaseFileError(
            "SQLite WAL-mode uploads are not supported. Upload a checkpointed database file."
        )

    try:
        with closing(_open_readonly(path)) as database:
            database.execute("PRAGMA trusted_schema=OFF")
            database.execute("PRAGMA query_only=ON")
            result = database.execute("PRAGMA quick_check").fetchone()
            if result is None or result[0] != "ok":
                raise InvalidDatabaseFileError(
                    "The uploaded SQLite database failed its integrity check."
                )
            database.execute("SELECT name FROM sqlite_master LIMIT 0").fetchall()
    except InvalidDatabaseFileError:
        raise
    except sqlite3.Error:
        raise InvalidDatabaseFileError(
            "The uploaded file is invalid, corrupted, or cannot be opened as SQLite."
        ) from None


def _open_readonly(path: Path) -> sqlite3.Connection:
    uri = f"{path.as_uri()}?mode=ro&immutable=1"
    return sqlite3.connect(uri, uri=True, timeout=5)


def create_sqlite_engine(path: Path) -> Engine:
    uri = f"{path.as_uri()}?mode=ro&immutable=1"

    engine = create_engine(
        "sqlite+pysqlite://",
        creator=lambda: sqlite3.connect(uri, uri=True, check_same_thread=False),
        poolclass=QueuePool,
        pool_size=1,
        max_overflow=0,
        pool_timeout=get_settings().database_connection_timeout_seconds,
        pool_pre_ping=True,
    )

    @event.listens_for(engine, "connect")
    def configure_read_only_sqlite(connection: sqlite3.Connection, _: object) -> None:
        connection.execute("PRAGMA trusted_schema=OFF")
        connection.execute("PRAGMA query_only=ON")
        connection.execute("PRAGMA foreign_keys=ON")

    return engine
