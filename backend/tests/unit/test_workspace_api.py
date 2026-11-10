from uuid import UUID, uuid4

import pytest

from app.db.models import DatabaseConnection, QueryHistory


def _create_connection(
    session_factory,
    *,
    user_id: UUID,
    name: str = "Workspace database",
) -> UUID:
    connection_id = uuid4()
    with session_factory() as session:
        session.add(
            DatabaseConnection(
                id=connection_id,
                user_id=user_id,
                name=name,
                database_type="sqlite",
                connection_metadata={},
            )
        )
        session.commit()
    return connection_id


@pytest.mark.usefixtures("connection_settings")
def test_query_history_search_filter_and_pagination(
    authenticated_client,
    test_session_factory,
) -> None:
    connection_id = _create_connection(
        test_session_factory,
        user_id=authenticated_client["user_id"],
    )
    with test_session_factory() as session:
        session.add_all(
            [
                QueryHistory(
                    user_id=authenticated_client["user_id"],
                    connection_id=connection_id,
                    natural_language_question=f"Revenue report {index}",
                    generated_sql="SELECT revenue FROM sales",
                    execution_status="succeeded" if index == 0 else "failed",
                    execution_duration=0.25,
                )
                for index in range(3)
            ]
        )
        session.commit()

    response = authenticated_client["client"](
        "GET",
        "/api/v1/history?page=1&page_size=1&status=failed&search=revenue",
        headers=authenticated_client["headers"],
    )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["total"] == 2
    assert len(body["items"]) == 1
    assert body["items"][0]["execution_status"] == "failed"
    assert body["items"][0]["execution_duration_ms"] == 250
    assert body["items"][0]["connection_name"] == "Workspace database"


def test_saved_query_create_update_delete_and_ownership(
    authenticated_client,
    api_client,
    test_session_factory,
) -> None:
    connection_id = _create_connection(
        test_session_factory,
        user_id=authenticated_client["user_id"],
    )
    headers = authenticated_client["headers"]
    created = authenticated_client["client"](
        "POST",
        "/api/v1/saved-queries",
        headers=headers,
        json={
            "connection_id": str(connection_id),
            "name": "  Sales by region  ",
            "description": "  Monthly report  ",
            "sql_query": "  SELECT region FROM sales  ",
        },
    )

    assert created.status_code == 201, created.text
    saved = created.json()
    assert saved["name"] == "Sales by region"
    assert saved["description"] == "Monthly report"
    assert saved["sql_query"] == "SELECT region FROM sales"

    updated = authenticated_client["client"](
        "PATCH",
        f"/api/v1/saved-queries/{saved['id']}",
        headers=headers,
        json={"name": "Regional sales", "description": None},
    )
    assert updated.status_code == 200, updated.text
    assert updated.json()["name"] == "Regional sales"
    assert updated.json()["description"] is None

    other_register = api_client(
        "POST",
        "/api/v1/auth/register",
        json={
            "username": "saved-other",
            "email": "saved-other@example.com",
            "password": "Another-strong-password-123",
        },
    )
    foreign_headers = authenticated_client["client"](
        "POST",
        "/api/v1/auth/login",
        json={
            "email": "saved-other@example.com",
            "password": "Another-strong-password-123",
        },
    ).json()
    hidden = api_client(
        "DELETE",
        f"/api/v1/saved-queries/{saved['id']}",
        headers={"Authorization": f"Bearer {foreign_headers['access_token']}"},
    )
    assert other_register.status_code == 201
    assert hidden.status_code == 404

    listed = authenticated_client["client"](
        "GET",
        "/api/v1/saved-queries?search=regional",
        headers=headers,
    )
    assert [item["id"] for item in listed.json()] == [saved["id"]]

    deleted = authenticated_client["client"](
        "DELETE",
        f"/api/v1/saved-queries/{saved['id']}",
        headers=headers,
    )
    assert deleted.status_code == 204
    assert authenticated_client["client"](
        "GET",
        "/api/v1/saved-queries",
        headers=headers,
    ).json() == []


def test_workspace_endpoints_require_authentication(api_client) -> None:
    assert api_client("GET", "/api/v1/history").status_code == 401
    assert api_client("GET", "/api/v1/saved-queries").status_code == 401
    assert api_client("POST", "/api/v1/saved-queries", json={}).status_code == 401

