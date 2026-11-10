import logging
import sqlite3
from pathlib import Path
from uuid import UUID

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.exc import SQLAlchemyError

from app.database_targets.connection_manager import ConnectionManager, connection_manager
from app.database_targets.exceptions import CredentialEncryptionError, TargetConnectionError
from app.database_targets.postgres_target import decrypt_password, encrypt_password
from app.db.models import DatabaseConnection


def sqlite_database_bytes(*, empty: bool = False) -> bytes:
    database = sqlite3.connect(":memory:")
    if not empty:
        database.executescript(
            """
            CREATE TABLE departments (
                id INTEGER PRIMARY KEY,
                name TEXT NOT NULL UNIQUE
            );
            CREATE TABLE employees (
                id INTEGER PRIMARY KEY,
                email TEXT NOT NULL UNIQUE,
                department_id INTEGER REFERENCES departments(id)
            );
            CREATE INDEX ix_employees_department ON employees(department_id);
            """
        )
    contents = database.serialize()
    database.close()
    return contents


def upload_database(authenticated_client, content: bytes, filename: str = "team.db"):
    client = authenticated_client["client"]
    return client(
        "POST",
        "/api/v1/connections/sqlite/upload",
        headers=authenticated_client["headers"],
        data={"name": "Team database"},
        files={"file": (filename, content, "application/octet-stream")},
    )


@pytest.mark.usefixtures("connection_settings")
def test_sqlite_upload_and_schema_inspection_returns_real_metadata(authenticated_client) -> None:
    upload = upload_database(authenticated_client, sqlite_database_bytes())

    assert upload.status_code == 201, upload.text
    connection_id = upload.json()["id"]
    listing = authenticated_client["client"](
        "GET",
        "/api/v1/connections",
        headers=authenticated_client["headers"],
    )
    schema = authenticated_client["client"](
        "GET",
        f"/api/v1/connections/{connection_id}/schema",
        headers=authenticated_client["headers"],
    )

    assert listing.status_code == 200
    assert listing.json()[0]["database_type"] == "sqlite"
    assert listing.json()[0]["connection_status"] == "connected"
    assert "file_key" not in str(listing.json())
    assert schema.status_code == 200
    tables = {table["name"]: table for table in schema.json()["schemas"][0]["tables"]}
    assert {"departments", "employees"} == set(tables)
    assert tables["employees"]["primary_key"] == ["id"]
    assert tables["employees"]["foreign_keys"][0]["referred_table"] == "departments"
    assert ["email"] in tables["employees"]["unique_constraints"]
    assert any(index["name"] == "ix_employees_department" for index in tables["employees"]["indexes"])


@pytest.mark.usefixtures("connection_settings")
def test_empty_sqlite_database_has_no_tables(authenticated_client) -> None:
    upload = upload_database(
        authenticated_client,
        sqlite_database_bytes(empty=True),
        "empty.sqlite",
    )

    assert upload.status_code == 201, upload.text
    response = authenticated_client["client"](
        "GET",
        f"/api/v1/connections/{upload.json()['id']}/schema",
        headers=authenticated_client["headers"],
    )
    assert response.status_code == 200
    assert response.json()["schemas"] == [{"name": "main", "tables": []}]


@pytest.mark.parametrize(
    ("filename", "content", "expected_status"),
    [
        ("bad.txt", b"not a database", 400),
        ("bad.db", b"not a database", 400),
        ("../escape.db", b"not a database", 400),
        (r"..\escape.db", b"not a database", 400),
    ],
)
def test_invalid_or_path_traversal_uploads_are_rejected(
    authenticated_client,
    connection_settings,
    filename: str,
    content: bytes,
    expected_status: int,
) -> None:
    sentinel = connection_settings.sqlite_upload_storage_dir.parent / "escape.db"
    sentinel.write_bytes(b"keep this file")

    response = upload_database(authenticated_client, content, filename)

    assert response.status_code == expected_status
    assert sentinel.read_bytes() == b"keep this file"
    assert list(connection_settings.sqlite_upload_storage_dir.glob("*.sqlite3")) == []


def test_oversized_sqlite_upload_is_rejected(authenticated_client, connection_settings) -> None:
    connection_settings.max_sqlite_upload_size_bytes = 100

    response = upload_database(authenticated_client, b"x" * 101)

    assert response.status_code == 413
    assert list(connection_settings.sqlite_upload_storage_dir.glob("*")) == []


def test_wal_mode_sqlite_upload_is_rejected_safely(
    authenticated_client, connection_settings, tmp_path: Path
) -> None:
    wal_path = tmp_path / "wal.sqlite"
    database = sqlite3.connect(wal_path)
    database.execute("PRAGMA journal_mode=WAL")
    database.execute("CREATE TABLE sample (id INTEGER PRIMARY KEY)")
    database.close()

    response = upload_database(authenticated_client, wal_path.read_bytes(), "wal.sqlite")

    assert response.status_code == 400
    assert "WAL-mode" in response.json()["detail"]
    assert list(connection_settings.sqlite_upload_storage_dir.glob("*")) == []


def test_uploads_use_distinct_managed_files_and_delete_cleans_file(
    authenticated_client, connection_settings
) -> None:
    first = upload_database(authenticated_client, sqlite_database_bytes())
    second = upload_database(authenticated_client, sqlite_database_bytes())
    assert first.status_code == 201
    assert second.status_code == 201
    files = list(connection_settings.sqlite_upload_storage_dir.glob("*.sqlite3"))
    assert len(files) == 2
    assert len(connection_manager._engines) == 2

    deleted = authenticated_client["client"](
        "DELETE",
        f"/api/v1/connections/{first.json()['id']}",
        headers=authenticated_client["headers"],
    )
    assert deleted.status_code == 204, deleted.text
    assert len(list(connection_settings.sqlite_upload_storage_dir.glob("*.sqlite3"))) == 1


def test_connection_endpoints_require_authentication(api_client) -> None:
    for method, path in (
        ("GET", "/api/v1/connections"),
        ("POST", "/api/v1/connections/sqlite/upload"),
        ("GET", f"/api/v1/connections/{UUID(int=1)}"),
        ("POST", f"/api/v1/connections/{UUID(int=1)}/test"),
        ("GET", f"/api/v1/connections/{UUID(int=1)}/schema"),
        ("DELETE", f"/api/v1/connections/{UUID(int=1)}"),
    ):
        response = api_client(method, path)
        assert response.status_code == 401


def test_connection_ownership_hides_other_users_resources(
    authenticated_client, api_client, connection_settings
) -> None:
    uploaded = upload_database(authenticated_client, sqlite_database_bytes())
    assert uploaded.status_code == 201

    second_register = api_client(
        "POST",
        "/api/v1/auth/register",
        json={
            "username": "second-owner",
            "email": "second@example.com",
            "password": "Another-password-123",
        },
    )
    second_login = api_client(
        "POST",
        "/api/v1/auth/login",
        json={"email": "second@example.com", "password": "Another-password-123"},
    )
    second_headers = {"Authorization": f"Bearer {second_login.json()['access_token']}"}

    for method, suffix in (
        ("GET", ""),
        ("GET", "/schema"),
        ("POST", "/test"),
        ("DELETE", ""),
    ):
        response = api_client(
            method,
            f"/api/v1/connections/{uploaded.json()['id']}{suffix}",
            headers=second_headers,
        )
        assert response.status_code == 404
    assert second_register.status_code == 201
    assert len(list(connection_settings.sqlite_upload_storage_dir.glob("*.sqlite3"))) == 1


@pytest.mark.usefixtures("connection_settings")
def test_sqlite_target_is_read_only(authenticated_client, test_session_factory) -> None:
    uploaded = upload_database(authenticated_client, sqlite_database_bytes())
    connection_id = uploaded.json()["id"]
    connection = authenticated_client["client"](
        "GET",
        f"/api/v1/connections/{connection_id}",
        headers=authenticated_client["headers"],
    )
    assert connection.status_code == 200
    with test_session_factory() as session:
        target = session.scalar(
            select(DatabaseConnection).where(
                DatabaseConnection.id == UUID(connection_id)
            )
        )
    target_engine = connection_manager.get_engine(target)
    with pytest.raises(SQLAlchemyError):
        with target_engine.begin() as database:
            database.exec_driver_sql("CREATE TABLE forbidden (id INTEGER)")
    connection_manager.dispose(UUID(connection_id))


@pytest.mark.usefixtures("connection_settings")
def test_postgresql_credentials_are_encrypted_and_never_returned(
    authenticated_client,
    test_session_factory,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    import app.services.connection_service as service

    monkeypatch.setattr(service, "create_postgres_engine", lambda **_: create_engine("sqlite://"))
    monkeypatch.setattr(service, "verify_postgres_engine", lambda _: None)
    password = "db-secret-never-return"
    payload = {
        "name": "Production",
        "host": "db.example.test",
        "port": 5432,
        "database_name": "analytics",
        "username": "app_reader",
        "password": password,
        "sslmode": "verify-full",
    }

    with caplog.at_level(logging.INFO):
        response = authenticated_client["client"](
            "POST",
            "/api/v1/connections/postgresql",
            headers=authenticated_client["headers"],
            json=payload,
        )

    assert response.status_code == 201, response.text
    assert password not in response.text
    assert password not in caplog.text
    with test_session_factory() as session:
        connection = session.scalar(
            select(DatabaseConnection).where(
                DatabaseConnection.id == UUID(response.json()["id"])
            )
        )
        ciphertext = connection.connection_metadata["password_encrypted"]
        assert ciphertext != password
        assert decrypt_password(ciphertext) == password
        assert "password" not in response.json()["metadata"]


def test_missing_credential_encryption_key_fails_closed(
    authenticated_client,
    connection_settings,
) -> None:
    connection_settings.postgres_credentials_encryption_key = ""
    response = authenticated_client["client"](
        "POST",
        "/api/v1/connections/postgresql",
        headers=authenticated_client["headers"],
        json={
            "name": "No key",
            "host": "localhost",
            "port": 5432,
            "database_name": "analytics",
            "username": "user",
            "password": "secret-password",
        },
    )

    assert response.status_code == 503
    assert "secret-password" not in response.text


@pytest.mark.usefixtures("connection_settings")
def test_postgresql_requires_tls_in_production(
    authenticated_client,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.core.config import get_settings

    monkeypatch.setattr(get_settings(), "app_env", "production")
    response = authenticated_client["client"](
        "POST",
        "/api/v1/connections/postgresql/test",
        headers=authenticated_client["headers"],
        json={
            "name": "Insecure connection",
            "host": "db.example.test",
            "port": 5432,
            "database_name": "analytics",
            "username": "app_reader",
            "password": "not-returned",
            "sslmode": "disable",
        },
    )

    assert response.status_code == 422
    assert "TLS" in response.json()["detail"]
    assert "not-returned" not in response.text

    saved = authenticated_client["client"](
        "POST",
        "/api/v1/connections/postgresql",
        headers=authenticated_client["headers"],
        json={
            "name": "Insecure connection",
            "host": "db.example.test",
            "port": 5432,
            "database_name": "analytics",
            "username": "app_reader",
            "password": "not-returned",
            "sslmode": "disable",
        },
    )

    assert saved.status_code == 422
    assert "TLS" in saved.json()["detail"]
    assert "not-returned" not in saved.text


@pytest.mark.usefixtures("connection_settings")
def test_postgres_input_validation_and_connection_failures_are_sanitized(
    authenticated_client,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import app.services.connection_service as service

    payload = {
        "name": "Remote",
        "host": "https://db.example.test/path",
        "port": 5432,
        "database_name": "analytics",
        "username": "reader",
        "password": "top-secret",
    }
    invalid = authenticated_client["client"](
        "POST",
        "/api/v1/connections/postgresql/test",
        headers=authenticated_client["headers"],
        json=payload,
    )
    assert invalid.status_code == 422
    assert "top-secret" not in invalid.text

    monkeypatch.setattr(
        service,
        "create_postgres_engine",
        lambda **_: create_engine("sqlite://"),
    )
    monkeypatch.setattr(
        service,
        "verify_postgres_engine",
        lambda _: (_ for _ in ()).throw(
            TargetConnectionError("The database connection could not be established.")
        ),
    )
    payload["host"] = "db.example.test"
    failed = authenticated_client["client"](
        "POST",
        "/api/v1/connections/postgresql/test",
        headers=authenticated_client["headers"],
        json=payload,
    )
    assert failed.status_code == 502
    assert "top-secret" not in failed.text


@pytest.mark.usefixtures("connection_settings")
def test_real_postgres_driver_failure_is_sanitized(
    authenticated_client,
    caplog: pytest.LogCaptureFixture,
) -> None:
    password = "do-not-log-this-postgres-password"
    response = authenticated_client["client"](
        "POST",
        "/api/v1/connections/postgresql/test",
        headers=authenticated_client["headers"],
        json={
            "name": "Unreachable local server",
            "host": "127.0.0.1",
            "port": 1,
            "database_name": "analytics",
            "username": "reader",
            "password": password,
        },
    )

    assert response.status_code == 502
    assert password not in response.text
    assert password not in caplog.text


def test_credential_encryption_requires_a_valid_key(
    connection_settings,
) -> None:
    connection_settings.postgres_credentials_encryption_key = "invalid-key"
    with pytest.raises(CredentialEncryptionError):
        encrypt_password("secret")


def test_connection_manager_disposes_cached_engines() -> None:
    manager = ConnectionManager()
    engine = create_engine("sqlite://")
    disposed = []
    engine.dispose = lambda: disposed.append(True)
    manager._create_engine = lambda _: engine
    connection = DatabaseConnection(
        id=UUID(int=10),
        user_id=UUID(int=11),
        name="mock target",
        database_type="postgresql",
        connection_metadata={},
    )
    manager.get_engine(connection)

    manager.dispose(connection.id)

    assert disposed == [True]
