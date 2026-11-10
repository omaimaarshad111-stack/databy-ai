from datetime import UTC, datetime
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status
from sqlalchemy.orm import Session

from app.api.dependencies import get_current_user
from app.core.config import get_settings
from app.database_targets.exceptions import (
    ConnectionCleanupError,
    ConnectionNotFoundError,
    CredentialEncryptionError,
    DatabaseTargetError,
    InvalidDatabaseFileError,
    TargetConnectionError,
    UploadTooLargeError,
)
from app.db.models import DatabaseConnection, User
from app.db.session import get_db
from app.schemas.connections import (
    ConnectionResponse,
    ConnectionTestResponse,
    DatabaseSchemaResponse,
    PostgreSQLConnectionInput,
    SQLiteUploadResponse,
)
from app.services.connection_service import (
    create_postgres_connection,
    create_sqlite_connection,
    delete_connection,
    get_owned_connection,
    inspect_connection_schema,
    list_connections,
    test_postgres_details,
    test_saved_connection,
)

router = APIRouter(prefix="/connections", tags=["database connections"])


def _connection_response(connection: DatabaseConnection) -> ConnectionResponse:
    metadata = connection.connection_metadata
    public_metadata: dict[str, str | int] = {}
    if connection.database_type == "postgresql":
        public_metadata = {
            "host": metadata["host"],
            "port": metadata["port"],
            "database_name": metadata["database_name"],
            "username": metadata["username"],
            "sslmode": metadata["sslmode"],
        }
    return ConnectionResponse(
        id=connection.id,
        name=connection.name,
        database_type=connection.database_type,
        connection_status=(
            None
            if connection.last_tested_at is None
            else "connected"
            if connection.last_test_succeeded
            else "failed"
        ),
        last_tested_at=connection.last_tested_at,
        metadata=public_metadata,
        created_at=connection.created_at,
        updated_at=connection.updated_at,
    )


def _not_found() -> HTTPException:
    return HTTPException(status_code=404, detail="Database connection not found.")


def _require_postgres_tls(details: PostgreSQLConnectionInput) -> None:
    if get_settings().app_env.lower() == "production" and details.sslmode in {
        "disable",
        "allow",
        "prefer",
    }:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="PostgreSQL connections must use TLS in production.",
        )


@router.post(
    "/sqlite/upload",
    response_model=SQLiteUploadResponse,
    status_code=status.HTTP_201_CREATED,
)
def upload_sqlite_database(
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
    name: Annotated[str, Form(min_length=1, max_length=120)],
    file: Annotated[UploadFile, File()],
) -> SQLiteUploadResponse:
    if not name.strip():
        raise HTTPException(status_code=422, detail="Connection name must not be blank.")
    try:
        connection = create_sqlite_connection(db, current_user, name, file)
    except UploadTooLargeError as exc:
        raise HTTPException(status_code=413, detail=str(exc)) from None
    except InvalidDatabaseFileError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from None
    except TargetConnectionError:
        raise HTTPException(
            status_code=400,
            detail="The uploaded SQLite database could not be opened safely.",
        ) from None
    return SQLiteUploadResponse(
        id=connection.id,
        name=connection.name,
        database_type="sqlite",
        connection_status="connected",
        last_tested_at=connection.last_tested_at or datetime.now(UTC),
        created_at=connection.created_at,
    )


@router.post("/postgresql/test", response_model=ConnectionTestResponse)
def test_postgresql_details(
    details: PostgreSQLConnectionInput,
    _: Annotated[User, Depends(get_current_user)],
) -> ConnectionTestResponse:
    _require_postgres_tls(details)
    try:
        test_postgres_details(details)
    except TargetConnectionError:
        raise HTTPException(
            status_code=502,
            detail="The PostgreSQL connection could not be established. Check the connection details and network access.",
        ) from None
    return ConnectionTestResponse(
        success=True,
        message="PostgreSQL connection succeeded.",
        last_tested_at=datetime.now(UTC),
    )


@router.post(
    "/postgresql",
    response_model=ConnectionResponse,
    status_code=status.HTTP_201_CREATED,
)
def save_postgresql_connection(
    details: PostgreSQLConnectionInput,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> ConnectionResponse:
    _require_postgres_tls(details)
    try:
        connection = create_postgres_connection(db, current_user, details)
    except CredentialEncryptionError:
        raise HTTPException(
            status_code=503,
            detail="PostgreSQL credential encryption is not configured correctly.",
        ) from None
    except TargetConnectionError:
        raise HTTPException(
            status_code=502,
            detail="The PostgreSQL connection could not be established. Check the connection details and network access.",
        ) from None
    return _connection_response(connection)


@router.get("", response_model=list[ConnectionResponse])
def get_connections(
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> list[ConnectionResponse]:
    return [_connection_response(connection) for connection in list_connections(db, current_user)]


@router.get("/{connection_id}", response_model=ConnectionResponse)
def get_connection(
    connection_id: UUID,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> ConnectionResponse:
    try:
        connection = get_owned_connection(db, current_user, connection_id)
    except ConnectionNotFoundError:
        raise _not_found() from None
    return _connection_response(connection)


@router.post("/{connection_id}/test", response_model=ConnectionTestResponse)
def test_saved_connection_endpoint(
    connection_id: UUID,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> ConnectionTestResponse:
    try:
        connection = get_owned_connection(db, current_user, connection_id)
    except ConnectionNotFoundError:
        raise _not_found() from None
    success = test_saved_connection(db, connection)
    if not success:
        return ConnectionTestResponse(
            success=False,
            message="The database connection could not be established.",
            last_tested_at=connection.last_tested_at or datetime.now(UTC),
        )
    return ConnectionTestResponse(
        success=True,
        message="Database connection succeeded.",
        last_tested_at=connection.last_tested_at or datetime.now(UTC),
    )


@router.get("/{connection_id}/schema", response_model=DatabaseSchemaResponse)
def get_connection_schema(
    connection_id: UUID,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> DatabaseSchemaResponse:
    try:
        connection = get_owned_connection(db, current_user, connection_id)
        schemas = inspect_connection_schema(connection)
    except ConnectionNotFoundError:
        raise _not_found() from None
    except (DatabaseTargetError, KeyError, ValueError):
        raise HTTPException(
            status_code=502,
            detail="The database schema could not be inspected.",
        ) from None
    return DatabaseSchemaResponse(
        connection_id=connection.id,
        database_type=connection.database_type,
        schemas=schemas,
    )


@router.delete("/{connection_id}", status_code=status.HTTP_204_NO_CONTENT)
def remove_connection(
    connection_id: UUID,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> None:
    try:
        connection = get_owned_connection(db, current_user, connection_id)
        delete_connection(db, connection)
    except ConnectionNotFoundError:
        raise _not_found() from None
    except ConnectionCleanupError:
        raise HTTPException(
            status_code=500,
            detail="The connection was deleted but its stored file needs cleanup.",
        ) from None
