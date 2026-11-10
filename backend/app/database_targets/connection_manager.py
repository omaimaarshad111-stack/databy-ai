from collections import OrderedDict
from threading import RLock
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.engine import Engine
from sqlalchemy.exc import SQLAlchemyError

from app.core.config import get_settings
from app.database_targets.exceptions import CredentialEncryptionError, TargetConnectionError
from app.database_targets.postgres_target import (
    create_postgres_engine,
    decrypt_password,
)
from app.database_targets.sqlite_target import create_sqlite_engine
from app.db.models import DatabaseConnection


class ConnectionManager:
    def __init__(self, max_engines: int = 32) -> None:
        self._max_engines = max_engines
        self._engines: OrderedDict[UUID, Engine] = OrderedDict()
        self._lock = RLock()

    def get_engine(self, connection: DatabaseConnection) -> Engine:
        with self._lock:
            engine = self._engines.pop(connection.id, None)
            if engine is not None:
                self._engines[connection.id] = engine
                return engine

            engine = self._create_engine(connection)
            self._engines[connection.id] = engine
            while len(self._engines) > self._max_engines:
                _, oldest_engine = self._engines.popitem(last=False)
                oldest_engine.dispose()
            return engine

    def test_connection(self, connection: DatabaseConnection) -> None:
        engine = self.get_engine(connection)
        try:
            with engine.connect() as database_connection:
                database_connection.execute(text("SELECT 1"))
        except (SQLAlchemyError, OSError, ValueError):
            self.dispose(connection.id)
            raise TargetConnectionError(
                "The database connection could not be established."
            ) from None

    def dispose(self, connection_id: UUID) -> None:
        with self._lock:
            engine = self._engines.pop(connection_id, None)
        if engine is not None:
            engine.dispose()

    def dispose_all(self) -> None:
        with self._lock:
            engines = list(self._engines.values())
            self._engines.clear()
        for engine in engines:
            engine.dispose()

    def _create_engine(self, connection: DatabaseConnection) -> Engine:
        settings = get_settings()
        if connection.database_type == "sqlite":
            file_key = connection.connection_metadata.get("file_key")
            if not isinstance(file_key, str) or not (
                len(file_key) == 40
                and file_key.endswith(".sqlite3")
                and all(character in "0123456789abcdef" for character in file_key[:-8])
            ):
                raise TargetConnectionError("The SQLite connection metadata is invalid.")
            storage_dir = settings.sqlite_upload_storage_dir.resolve()
            path = storage_dir / file_key
            if (
                path.is_symlink()
                or not path.is_file()
                or path.resolve(strict=True).parent != storage_dir
            ):
                raise TargetConnectionError("The uploaded database is unavailable.")
            return create_sqlite_engine(path)

        if connection.database_type != "postgresql":
            raise TargetConnectionError("The database type is unsupported.")

        metadata = connection.connection_metadata
        try:
            password = decrypt_password(metadata["password_encrypted"])
            return create_postgres_engine(
                username=metadata["username"],
                password=password,
                host=metadata["host"],
                port=int(metadata["port"]),
                database_name=metadata["database_name"],
                sslmode=metadata["sslmode"],
            )
        except (KeyError, TypeError, ValueError, CredentialEncryptionError):
            raise TargetConnectionError(
                "The saved PostgreSQL connection is invalid."
            ) from None


connection_manager = ConnectionManager()
