from datetime import UTC, datetime
import logging
from pathlib import Path
import os
import tempfile
from uuid import UUID, uuid4

from fastapi import UploadFile
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.database_targets.connection_manager import connection_manager
from app.database_targets.exceptions import (
    ConnectionCleanupError,
    ConnectionNotFoundError,
    InvalidDatabaseFileError,
    TargetConnectionError,
    UploadTooLargeError,
)
from app.database_targets.postgres_target import (
    create_postgres_engine,
    encrypt_password,
    verify_postgres_engine,
)
from app.database_targets.schema_inspector import inspect_database_schema
from app.database_targets.sqlite_target import validate_sqlite_file
from app.db.models import DatabaseConnection, User
from app.schemas.connections import PostgreSQLConnectionInput, SchemaInfo

ALLOWED_SQLITE_EXTENSIONS = {".db", ".sqlite", ".sqlite3"}
logger = logging.getLogger(__name__)


def list_connections(db: Session, user: User) -> list[DatabaseConnection]:
    return list(
        db.scalars(
            select(DatabaseConnection)
            .where(DatabaseConnection.user_id == user.id)
            .order_by(DatabaseConnection.created_at.desc())
        )
    )


def get_owned_connection(
    db: Session,
    user: User,
    connection_id: UUID,
) -> DatabaseConnection:
    connection = db.scalar(
        select(DatabaseConnection).where(
            DatabaseConnection.id == connection_id,
            DatabaseConnection.user_id == user.id,
        )
    )
    if connection is None:
        raise ConnectionNotFoundError
    return connection


def create_postgres_connection(
    db: Session,
    user: User,
    details: PostgreSQLConnectionInput,
) -> DatabaseConnection:
    password = details.password.get_secret_value()
    password_encrypted = encrypt_password(password)
    engine = create_postgres_engine(
        username=details.username,
        password=password,
        host=details.host,
        port=details.port,
        database_name=details.database_name,
        sslmode=details.sslmode,
    )
    try:
        verify_postgres_engine(engine)
    finally:
        engine.dispose()

    connection = DatabaseConnection(
        id=uuid4(),
        user_id=user.id,
        name=details.name,
        database_type="postgresql",
        connection_metadata={
            "host": details.host,
            "port": details.port,
            "database_name": details.database_name,
            "username": details.username,
            "sslmode": details.sslmode,
            "password_encrypted": password_encrypted,
        },
        last_tested_at=datetime.now(UTC),
        last_test_succeeded=True,
    )
    db.add(connection)
    db.commit()
    db.refresh(connection)
    return connection


def test_postgres_details(details: PostgreSQLConnectionInput) -> None:
    engine = create_postgres_engine(
        username=details.username,
        password=details.password.get_secret_value(),
        host=details.host,
        port=details.port,
        database_name=details.database_name,
        sslmode=details.sslmode,
    )
    try:
        verify_postgres_engine(engine)
    finally:
        engine.dispose()


def create_sqlite_connection(
    db: Session,
    user: User,
    name: str,
    upload: UploadFile,
) -> DatabaseConnection:
    original_filename = upload.filename
    if (
        not original_filename
        or "/" in original_filename
        or "\\" in original_filename
        or Path(original_filename).suffix.lower() not in ALLOWED_SQLITE_EXTENSIONS
    ):
        raise InvalidDatabaseFileError(
            "Upload a SQLite database file with a .db, .sqlite, or .sqlite3 extension."
        )
    normalized_name = name.strip()
    if not normalized_name:
        raise InvalidDatabaseFileError("Connection name must not be blank.")

    settings = get_settings()
    storage_dir = settings.sqlite_upload_storage_dir.resolve()
    storage_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
    if os.name != "nt":
        storage_dir.chmod(0o700)
    temporary_path: Path | None = None
    final_path: Path | None = None
    connection_id: UUID | None = None

    try:
        file_descriptor, temporary_name = tempfile.mkstemp(
            prefix=".upload-",
            suffix=".tmp",
            dir=storage_dir,
        )
        temporary_path = Path(temporary_name)
        size = 0
        with os.fdopen(file_descriptor, "wb") as target:
            while chunk := upload.file.read(64 * 1024):
                size += len(chunk)
                if size > settings.max_sqlite_upload_size_bytes:
                    raise UploadTooLargeError("The uploaded database exceeds the size limit.")
                target.write(chunk)

        validate_sqlite_file(temporary_path)
        file_key = f"{uuid4().hex}.sqlite3"
        final_path = storage_dir / file_key
        os.replace(temporary_path, final_path)
        temporary_path = None

        connection = DatabaseConnection(
            id=uuid4(),
            user_id=user.id,
            name=normalized_name,
            database_type="sqlite",
            connection_metadata={"file_key": file_key},
        )
        connection_id = connection.id
        connection_manager.test_connection(connection)
        inspect_database_schema(connection_manager.get_engine(connection))
        connection.last_tested_at = datetime.now(UTC)
        connection.last_test_succeeded = True
        db.add(connection)
        db.commit()
        db.refresh(connection)
        return connection
    except IntegrityError:
        db.rollback()
        raise
    except Exception:
        db.rollback()
        if final_path is not None:
            if connection_id is not None:
                connection_manager.dispose(connection_id)
            final_path.unlink(missing_ok=True)
        raise
    finally:
        if temporary_path is not None:
            temporary_path.unlink(missing_ok=True)


def test_saved_connection(
    db: Session,
    connection: DatabaseConnection,
) -> bool:
    now = datetime.now(UTC)
    try:
        connection_manager.test_connection(connection)
    except TargetConnectionError:
        connection.last_tested_at = now
        connection.last_test_succeeded = False
        db.commit()
        return False
    connection.last_tested_at = now
    connection.last_test_succeeded = True
    db.commit()
    return True


def inspect_connection_schema(
    connection: DatabaseConnection,
) -> list[SchemaInfo]:
    engine = connection_manager.get_engine(connection)
    return inspect_database_schema(engine)


def delete_connection(
    db: Session,
    connection: DatabaseConnection,
) -> None:
    file_path: Path | None = None
    if connection.database_type == "sqlite":
        file_key = connection.connection_metadata.get("file_key")
        if not isinstance(file_key, str) or not (
            len(file_key) == 40
            and file_key.endswith(".sqlite3")
            and all(character in "0123456789abcdef" for character in file_key[:-8])
        ):
            raise ConnectionCleanupError("The uploaded database could not be safely removed.")
        storage_dir = get_settings().sqlite_upload_storage_dir.resolve()
        file_path = storage_dir / file_key
        if file_path.is_symlink() or file_path.parent.resolve() != storage_dir:
            raise ConnectionCleanupError("The uploaded database could not be safely removed.")

    connection_id = connection.id
    db.delete(connection)
    db.commit()
    connection_manager.dispose(connection_id)

    if file_path is not None:
        try:
            file_path.unlink(missing_ok=True)
        except OSError as exc:
            logger.error(
                "Uploaded SQLite cleanup failed (%s, file_exists=%s).",
                type(exc).__name__,
                file_path.exists(),
            )
            raise ConnectionCleanupError(
                "The connection was deleted but its stored file needs cleanup."
            ) from None
