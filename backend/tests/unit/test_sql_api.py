import sqlite3
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

import pytest
from sqlalchemy import event

from app.database_targets.connection_manager import connection_manager
from app.db.models import DatabaseConnection
from app.schemas.connections import ColumnSchema, SchemaInfo, TableSchema
from app.sql.schemas import SQLGenerationDraft


class FakeStructuredModel:
    def __init__(self) -> None:
        self.prompts: list[object] = []

    def invoke(self, prompt: object) -> SQLGenerationDraft:
        self.prompts.append(prompt)
        return SQLGenerationDraft(
            status="success",
            generated_sql="SELECT name FROM customers ORDER BY name LIMIT 5",
            explanation="Lists customer names.",
        )


def _create_upload_database(path: Path) -> None:
    with sqlite3.connect(path) as database:
        database.execute(
            "CREATE TABLE customers (id INTEGER PRIMARY KEY, name TEXT NOT NULL)"
        )
        database.execute(
            "INSERT INTO customers (name) VALUES ('row-content-must-not-reach-model')"
        )


def _upload_connection(authenticated_client, tmp_path: Path) -> UUID:
    source_path = tmp_path / "source.sqlite3"
    _create_upload_database(source_path)
    with source_path.open("rb") as source:
        response = authenticated_client["client"](
            "POST",
            "/api/v1/connections/sqlite/upload",
            headers=authenticated_client["headers"],
            data={"name": "SQL API target"},
            files={"file": ("source.sqlite3", source, "application/octet-stream")},
        )
    assert response.status_code == 201, response.text
    return UUID(response.json()["id"])


@pytest.mark.usefixtures("connection_settings")
def test_generate_sql_uses_actual_schema_and_never_executes_generated_sql(
    authenticated_client,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.sql import generator

    connection_id = _upload_connection(
        authenticated_client,
        tmp_path,
    )
    model = FakeStructuredModel()
    monkeypatch.setattr(generator, "get_sql_model", lambda: model)

    engine = connection_manager._engines[connection_id]
    executed_statements: list[str] = []
    monkeypatch.setattr(
        connection_manager,
        "test_connection",
        lambda connection: pytest.fail(
            f"SQL generation unexpectedly tested {type(connection).__name__}."
        ),
    )

    def record_statement(*args: Any) -> None:
        statement = args[2]
        executed_statements.append(statement)

    event.listen(engine, "before_cursor_execute", record_statement)
    try:
        generated = authenticated_client["client"](
            "POST",
            f"/api/v1/connections/{connection_id}/generate-sql",
            headers=authenticated_client["headers"],
            json={"question": "List customer names"},
        )
        validated = authenticated_client["client"](
            "POST",
            "/api/v1/sql/validate",
            headers=authenticated_client["headers"],
            json={
                "connection_id": str(connection_id),
                "sql_query": "SELECT name FROM customers ORDER BY name LIMIT 5",
            },
        )
    finally:
        event.remove(engine, "before_cursor_execute", record_statement)

    assert generated.status_code == 200, generated.text
    assert generated.json()["status"] == "success"
    assert generated.json()["validation_status"] == "valid"
    assert validated.status_code == 200, validated.text
    assert validated.json()["is_valid"] is True
    prompt_content = str(model.prompts[0])
    assert "customers" in prompt_content
    assert "row-content-must-not-reach-model" not in prompt_content
    assert "password_encrypted" not in prompt_content
    assert "SELECT name FROM customers ORDER BY name LIMIT 5" not in executed_statements


def test_database_credentials_and_token_are_not_sent_to_the_model(
    authenticated_client,
    test_session_factory,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.api.v1 import sql as sql_api
    from app.sql import generator

    secrets = (
        "db-host-internal.example",
        "db-login-secret",
        "ciphertext-credential-placeholder",
        authenticated_client["headers"]["Authorization"].removeprefix("Bearer "),
    )
    connection = DatabaseConnection(
        id=uuid4(),
        user_id=authenticated_client["user_id"],
        name="Credential isolation test",
        database_type="postgresql",
        connection_metadata={
            "host": secrets[0],
            "port": 5432,
            "database_name": "analytics",
            "username": secrets[1],
            "password_encrypted": secrets[2],
            "sslmode": "require",
        },
    )
    with test_session_factory() as session:
        session.add(connection)
        session.commit()

    schemas = [
        SchemaInfo(
            name="public",
            tables=[
                TableSchema(
                    name="customers",
                    columns=[ColumnSchema(name="name", data_type="TEXT", nullable=False)],
                    primary_key=[],
                    foreign_keys=[],
                    unique_constraints=[],
                    indexes=[],
                )
            ],
        )
    ]
    model = FakeStructuredModel()

    def fake_inspect_schema(owned_connection):
        assert owned_connection.id == connection.id
        return schemas

    monkeypatch.setattr(sql_api, "inspect_connection_schema", fake_inspect_schema)
    monkeypatch.setattr(generator, "get_sql_model", lambda: model)

    response = authenticated_client["client"](
        "POST",
        f"/api/v1/connections/{connection.id}/generate-sql",
        headers=authenticated_client["headers"],
        json={"question": "List customer names"},
    )

    assert response.status_code == 200, response.text
    prompt_content = str(model.prompts[0])
    assert all(secret not in prompt_content for secret in secrets)
    assert all(secret not in response.text for secret in secrets)


@pytest.mark.usefixtures("connection_settings")
def test_generate_sql_requires_auth_and_owned_connection(
    api_client,
    authenticated_client,
    tmp_path: Path,
) -> None:
    connection_id = _upload_connection(authenticated_client, tmp_path)

    unauthenticated = api_client(
        "POST",
        f"/api/v1/connections/{connection_id}/generate-sql",
        json={"question": "List customer names"},
    )
    other_user_registration = api_client(
        "POST",
        "/api/v1/auth/register",
        json={
            "username": "different-owner",
            "email": "different-owner@example.com",
            "password": "Another-strong-password-123",
        },
    )
    assert other_user_registration.status_code == 201
    other_login = api_client(
        "POST",
        "/api/v1/auth/login",
        json={
            "email": "different-owner@example.com",
            "password": "Another-strong-password-123",
        },
    )
    other_headers = {
        "Authorization": f"Bearer {other_login.json()['access_token']}"
    }

    cross_user = api_client(
        "POST",
        "/api/v1/sql/validate",
        headers=other_headers,
        json={
            "connection_id": str(connection_id),
            "sql_query": "SELECT 1",
        },
    )

    assert unauthenticated.status_code == 401
    assert cross_user.status_code == 404


@pytest.mark.usefixtures("connection_settings")
def test_validation_endpoint_returns_invalid_sql_result(
    authenticated_client,
    tmp_path: Path,
) -> None:
    connection_id = _upload_connection(authenticated_client, tmp_path)

    response = authenticated_client["client"](
        "POST",
        "/api/v1/sql/validate",
        headers=authenticated_client["headers"],
        json={
            "connection_id": str(connection_id),
            "sql_query": "DROP TABLE customers",
        },
    )

    assert response.status_code == 200
    assert response.json()["is_valid"] is False
    assert "Only read-only SELECT queries are allowed." in response.json()["validation_errors"]


@pytest.mark.usefixtures("connection_settings")
def test_missing_groq_key_is_a_clear_service_error(
    authenticated_client,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.core.config import get_settings

    settings = get_settings()
    monkeypatch.setattr(settings, "groq_api_key", "")
    connection_id = _upload_connection(authenticated_client, tmp_path)

    response = authenticated_client["client"](
        "POST",
        f"/api/v1/connections/{connection_id}/generate-sql",
        headers=authenticated_client["headers"],
        json={"question": "List customer names"},
    )

    assert response.status_code == 503
    assert "GROQ_API_KEY" in response.json()["detail"]
