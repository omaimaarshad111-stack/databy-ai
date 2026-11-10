import json
import sqlite3
from pathlib import Path
from uuid import UUID

import pytest
from sqlalchemy import select

from app.agent.intent import IntentClassification
from app.db.models import Conversation, QueryHistory
from app.sql.schemas import SQLGenerationDraft


class FakeSQLModel:
    def __init__(self, sql: str) -> None:
        self.sql = sql
        self.prompts: list[object] = []

    def invoke(self, prompt: object) -> SQLGenerationDraft:
        self.prompts.append(prompt)
        return SQLGenerationDraft(
            status="success",
            generated_sql=self.sql,
            explanation="Returns matching customers.",
        )


def _connection(authenticated_client, tmp_path: Path) -> UUID:
    source = tmp_path / "assistant-source.sqlite3"
    with sqlite3.connect(source) as database:
        database.execute(
            "CREATE TABLE customers (id INTEGER PRIMARY KEY, name TEXT NOT NULL)"
        )
        database.executemany(
            "INSERT INTO customers (name) VALUES (?)",
            [("Avery",), ("private_customer_value",)],
        )
    with source.open("rb") as stream:
        response = authenticated_client["client"](
            "POST",
            "/api/v1/connections/sqlite/upload",
            headers=authenticated_client["headers"],
            data={"name": "Assistant target"},
            files={"file": ("assistant-source.sqlite3", stream, "application/octet-stream")},
        )
    assert response.status_code == 201, response.text
    return UUID(response.json()["id"])


def _sse_events(response_text: str) -> list[tuple[str, dict[str, object]]]:
    result: list[tuple[str, dict[str, object]]] = []
    for event in response_text.strip().split("\n\n"):
        lines = event.splitlines()
        name = next(line[7:] for line in lines if line.startswith("event: "))
        data = "\n".join(line[6:] for line in lines if line.startswith("data: "))
        result.append((name, json.loads(data)))
    return result


@pytest.mark.usefixtures("connection_settings")
def test_assistant_stream_executes_read_only_query_and_persists_history(
    authenticated_client,
    test_session_factory,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.agent.nodes import steps
    from app.sql import generator

    connection_id = _connection(authenticated_client, tmp_path)
    conversation_response = authenticated_client["client"](
        "POST",
        "/api/v1/assistant/conversations",
        headers=authenticated_client["headers"],
        json={"title": "Customer questions"},
    )
    assert conversation_response.status_code == 201, conversation_response.text
    conversation_id = conversation_response.json()["id"]

    monkeypatch.setattr(
        steps,
        "classify_intent",
        lambda question, context: IntentClassification(
            intent="database_query",
            user_facing_message="I will query the connected database.",
        ),
    )
    fake_model = FakeSQLModel(
        "SELECT name FROM customers ORDER BY name LIMIT 10"
    )
    monkeypatch.setattr(generator, "get_sql_model", lambda: fake_model)

    response = authenticated_client["client"](
        "POST",
        f"/api/v1/assistant/conversations/{conversation_id}/messages",
        headers=authenticated_client["headers"],
        json={
            "connection_id": str(connection_id),
            "content": "List the customer names",
        },
    )

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")
    events = _sse_events(response.text)
    event_names = [name for name, _ in events]
    assert event_names[:-1] == ["progress"] * 7
    assert event_names[-1] == "complete"
    completion = events[-1][1]
    assert completion["workflow_status"] == "completed"
    assert completion["validation_status"] == "valid"
    assert completion["execution"]["status"] == "success"
    assert completion["execution"]["row_count"] == 2
    assert completion["execution"]["rows"] == [["Avery"], ["private_customer_value"]]
    assert all(
        "private_customer_value" not in str(prompt)
        for prompt in fake_model.prompts
    )

    with test_session_factory() as session:
        history = session.scalar(
            select(QueryHistory).where(
                QueryHistory.conversation_id == UUID(conversation_id)
            )
        )
        conversation = session.get(Conversation, UUID(conversation_id))
        assert history is not None
        assert history.execution_status == "succeeded"
        assert history.natural_language_question == "List the customer names"
        assert "private_customer_value" not in history.generated_sql
        assert conversation is not None
        assert conversation.title == "Customer questions"
        assert session.scalar(
            select(QueryHistory.generated_sql).where(QueryHistory.id == history.id)
        )

    detail = authenticated_client["client"](
        "GET",
        f"/api/v1/assistant/conversations/{conversation_id}",
        headers=authenticated_client["headers"],
    )
    assert detail.status_code == 200
    assert [message["role"] for message in detail.json()["messages"]] == [
        "user",
        "assistant",
    ]


@pytest.mark.usefixtures("connection_settings")
def test_assistant_rejects_generated_write_and_never_executes_it(
    authenticated_client,
    test_session_factory,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.agent.nodes import steps
    from app.sql import generator

    connection_id = _connection(authenticated_client, tmp_path)
    conversation = authenticated_client["client"](
        "POST",
        "/api/v1/assistant/conversations",
        headers=authenticated_client["headers"],
        json={},
    ).json()
    monkeypatch.setattr(
        steps,
        "classify_intent",
        lambda question, context: IntentClassification(
            intent="database_query",
            user_facing_message="Read-only database question.",
        ),
    )
    monkeypatch.setattr(
        generator,
        "get_sql_model",
        lambda: FakeSQLModel("DELETE FROM customers"),
    )

    response = authenticated_client["client"](
        "POST",
        f"/api/v1/assistant/conversations/{conversation['id']}/messages",
        headers=authenticated_client["headers"],
        json={
            "connection_id": str(connection_id),
            "content": "Remove all customers",
        },
    )

    assert response.status_code == 200, response.text
    events = _sse_events(response.text)
    completion = events[-1][1]
    assert completion["workflow_status"] == "completed"
    assert completion["validation_status"] == "invalid"
    assert completion["execution"] is None
    assert "not executed" in completion["message"]["content"]
    with test_session_factory() as session:
        assert session.scalar(select(QueryHistory.id)) is None


def test_conversation_endpoints_require_authentication(api_client) -> None:
    create = api_client("POST", "/api/v1/assistant/conversations", json={})
    listing = api_client("GET", "/api/v1/assistant/conversations")
    message = api_client(
        "POST",
        "/api/v1/assistant/conversations/00000000-0000-0000-0000-000000000001/messages",
        json={
            "connection_id": "00000000-0000-0000-0000-000000000002",
            "content": "List customers",
        },
    )
    assert create.status_code == listing.status_code == message.status_code == 401


def test_conversation_and_connection_ownership_are_enforced(
    authenticated_client,
    api_client,
    tmp_path: Path,
    connection_settings,
) -> None:
    connection_id = _connection(authenticated_client, tmp_path)
    conversation = authenticated_client["client"](
        "POST",
        "/api/v1/assistant/conversations",
        headers=authenticated_client["headers"],
        json={},
    ).json()
    registration = api_client(
        "POST",
        "/api/v1/auth/register",
        json={
            "username": "assistant-other",
            "email": "assistant-other@example.com",
            "password": "Another-strong-password-123",
        },
    )
    login = api_client(
        "POST",
        "/api/v1/auth/login",
        json={
            "email": "assistant-other@example.com",
            "password": "Another-strong-password-123",
        },
    )
    headers = {"Authorization": f"Bearer {login.json()['access_token']}"}
    other_conversation = api_client(
        "POST",
        "/api/v1/assistant/conversations",
        headers=headers,
        json={},
    )

    hidden_conversation = api_client(
        "GET",
        f"/api/v1/assistant/conversations/{conversation['id']}",
        headers=headers,
    )
    hidden_connection = api_client(
        "POST",
        f"/api/v1/assistant/conversations/{other_conversation.json()['id']}/messages",
        headers=headers,
        json={"connection_id": str(connection_id), "content": "List customers"},
    )
    assert registration.status_code == 201
    assert other_conversation.status_code == 201
    assert hidden_conversation.status_code == 404
    assert hidden_connection.status_code == 404
