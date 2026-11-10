from datetime import date, datetime, time, timezone
from decimal import Decimal
import sqlite3
from pathlib import Path
from uuid import UUID, uuid4

import pytest
from sqlalchemy import select

from app.core.config import get_settings
from app.database_targets.connection_manager import connection_manager
from app.database_targets.sqlite_target import create_sqlite_engine
from app.db.models import Conversation, QueryHistory
from app.sql.execution_limits import ExecutionLimits, TooManyConcurrentExecutionsError, UserExecutionLimiter
from app.sql.executor import (
    QueryExecutionTimeoutError,
    _bounded_query,
    execute_validated_sql,
)
from app.database_targets.schema_inspector import inspect_database_schema
from app.sql.validator import validate_read_only_sql
from app.sql.result_formatter import serialize_value


def create_target_file(path: Path, *, rows: int = 4) -> None:
    with sqlite3.connect(path) as database:
        database.executescript(
            """
            CREATE TABLE customers (id INTEGER PRIMARY KEY, name TEXT, joined TEXT);
            CREATE TABLE orders (
                id INTEGER PRIMARY KEY,
                customer_id INTEGER NOT NULL REFERENCES customers(id),
                total REAL
            );
            INSERT INTO customers (name, joined) VALUES
                ('Ada', '2025-01-01'), ('Lin', '2025-02-01'),
                ('Sam', NULL), ('Jo', '2025-03-01');
            INSERT INTO orders (customer_id, total) VALUES
                (1, 25.50), (1, 10.00), (2, 8.25);
            """
        )
        if rows > 4:
            database.executemany(
                "INSERT INTO customers (name, joined) VALUES (?, NULL)",
                [(f"user-{index}",) for index in range(rows - 4)],
            )


@pytest.fixture
def uploaded_sqlite(
    authenticated_client,
    connection_settings,
    tmp_path: Path,
) -> str:
    path = tmp_path / "execution-target.sqlite3"
    create_target_file(path)
    with path.open("rb") as source:
        response = authenticated_client["client"](
            "POST",
            "/api/v1/connections/sqlite/upload",
            headers=authenticated_client["headers"],
            data={"name": "Execution test"},
            files={"file": (path.name, source, "application/octet-stream")},
        )
    assert response.status_code == 201, response.text
    return response.json()["id"]


def execute_request(authenticated_client, connection_id: str, query: str, **kwargs):
    return authenticated_client["client"](
        "POST",
        f"/api/v1/connections/{connection_id}/execute",
        headers=authenticated_client["headers"],
        json={"sql_query": query, **kwargs},
    )


def test_real_sqlite_select_where_join_group_order_cte_and_history(
    authenticated_client,
    uploaded_sqlite: str,
    test_session_factory,
) -> None:
    conversation_id = uuid4()
    with test_session_factory() as session:
        session.add(
            Conversation(
                id=conversation_id,
                user_id=authenticated_client["user_id"],
                title="Execution test",
            )
        )
        session.commit()
    query = """
        WITH spending AS (
            SELECT customer_id, SUM(total) AS amount
            FROM orders
            WHERE total > 5
            GROUP BY customer_id
        )
        SELECT customers.name, spending.amount
        FROM customers
        JOIN spending ON spending.customer_id = customers.id
        ORDER BY spending.amount DESC
    """

    response = execute_request(
        authenticated_client,
        uploaded_sqlite,
        query,
        conversation_id=str(conversation_id),
    )

    assert response.status_code == 200, response.text
    result = response.json()
    assert result["status"] == "success"
    assert result["columns"] == [
        {"name": "name", "data_type": None},
        {"name": "amount", "data_type": None},
    ]
    assert result["rows"] == [["Ada", 35.5], ["Lin", 8.25]]
    assert result["row_count"] == 2
    assert result["truncated"] is False
    with test_session_factory() as session:
        history = session.get(QueryHistory, UUID(result["execution_id"]))
        assert history is not None
        assert history.execution_status == "succeeded"
        assert history.conversation_id == conversation_id
        assert history.generated_sql is not None
        assert "total > 0" in history.generated_sql
        assert "[redacted]" not in history.generated_sql
        assert history.natural_language_question == "Manual SQL execution"
        assert not hasattr(history, "rows")

    fetched = authenticated_client["client"](
        "GET",
        f"/api/v1/executions/{result['execution_id']}",
        headers=authenticated_client["headers"],
    )
    assert fetched.status_code == 200
    assert fetched.json()["rows"] == result["rows"]


def test_empty_null_duplicate_columns_and_pagination(
    authenticated_client,
    uploaded_sqlite: str,
) -> None:
    empty = execute_request(
        authenticated_client,
        uploaded_sqlite,
        "SELECT id, name FROM customers WHERE id < 0",
    )
    nulls = execute_request(
        authenticated_client,
        uploaded_sqlite,
        "SELECT name, joined FROM customers WHERE id = 3",
    )
    duplicates = execute_request(
        authenticated_client,
        uploaded_sqlite,
        "SELECT id, id FROM customers ORDER BY id",
        page_size=2,
    )

    assert empty.json()["status"] == "success"
    assert empty.json()["columns"][0]["name"] == "id"
    assert empty.json()["rows"] == []
    assert nulls.json()["rows"] == [["Sam", None]]
    assert duplicates.json()["columns"][0]["name"] == "id"
    assert duplicates.json()["columns"][1]["name"] == "id_2"
    assert duplicates.json()["row_count"] == 2
    assert duplicates.json()["truncated"] is True


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (date(2025, 1, 2), "2025-01-02"),
        (datetime(2025, 1, 2, 3, 4, tzinfo=timezone.utc), "2025-01-02T03:04:00+00:00"),
        (time(3, 4, 5), "03:04:05"),
        (Decimal("10.250"), "10.250"),
        (uuid4(), None),
        (b"data", "ZGF0YQ=="),
        (float("inf"), "inf"),
        (None, None),
    ],
)
def test_result_values_are_json_safe(value, expected) -> None:
    actual = serialize_value(value)
    if expected is None and value is not None:
        assert actual == str(value)
    else:
        assert actual == expected


def test_result_window_preserves_order_and_existing_sql_limit() -> None:
    bounded = _bounded_query(
        "SELECT id FROM customers ORDER BY id LIMIT 10 OFFSET 4",
        "sqlite",
        page_size=3,
        offset=2,
    )

    assert "ORDER BY id LIMIT 6 OFFSET 6" in bounded
    assert "FROM (" not in bounded


def test_execution_rejects_writes_multiple_statements_and_dangerous_functions(
    authenticated_client,
    uploaded_sqlite: str,
    test_session_factory,
) -> None:
    for query in (
        "DELETE FROM customers",
        "SELECT id FROM customers; SELECT id FROM orders",
        "SELECT load_extension('extension')",
    ):
        response = execute_request(authenticated_client, uploaded_sqlite, query)
        assert response.status_code == 200
        assert response.json()["status"] == "rejected"

    with test_session_factory() as session:
        history = list(
            session.scalars(
                select(QueryHistory).where(
                    QueryHistory.connection_id == UUID(uploaded_sqlite)
                )
            )
        )
        assert len(history) == 3
        assert all(record.execution_status == "failed" for record in history)


def test_execution_and_result_retrieval_are_connection_owned(
    api_client,
    authenticated_client,
    uploaded_sqlite: str,
) -> None:
    register = api_client(
        "POST",
        "/api/v1/auth/register",
        json={
            "username": "other-runner",
            "email": "other-runner@example.com",
            "password": "Another-strong-password-123",
        },
    )
    login = api_client(
        "POST",
        "/api/v1/auth/login",
        json={
            "email": "other-runner@example.com",
            "password": "Another-strong-password-123",
        },
    )
    other_headers = {"Authorization": f"Bearer {login.json()['access_token']}"}

    unauthenticated = api_client(
        "POST",
        f"/api/v1/connections/{uploaded_sqlite}/execute",
        json={"sql_query": "SELECT 1"},
    )
    unauthenticated_result = api_client(
        "GET",
        "/api/v1/executions/00000000-0000-0000-0000-000000000001",
    )
    cross_user = api_client(
        "POST",
        f"/api/v1/connections/{uploaded_sqlite}/execute",
        headers=other_headers,
        json={"sql_query": "SELECT 1"},
    )
    owned_result = execute_request(authenticated_client, uploaded_sqlite, "SELECT 1")
    cross_user_result = api_client(
        "GET",
        f"/api/v1/executions/{owned_result.json()['execution_id']}",
        headers=other_headers,
    )

    assert register.status_code == 201
    assert unauthenticated.status_code == 401
    assert unauthenticated_result.status_code == 401
    assert cross_user.status_code == 404
    assert cross_user_result.status_code == 404


def test_query_timeout_interrupts_sqlite_execution(
    connection_settings,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = get_settings()
    monkeypatch.setattr(settings, "sql_execution_timeout_seconds", 0.05)
    target_path = tmp_path / "large-target.sqlite3"
    create_target_file(target_path, rows=1000)
    engine = create_sqlite_engine(target_path)
    limits = ExecutionLimits.from_settings()
    query = "SELECT COUNT(*) FROM customers a CROSS JOIN customers b CROSS JOIN customers c"

    try:
        schema = inspect_database_schema(engine)
        assert validate_read_only_sql(query, "sqlite", schema).is_valid
        with pytest.raises(QueryExecutionTimeoutError):
            execute_validated_sql(
                engine,
                "sqlite",
                query,
                page_size=10,
                offset=0,
                limits=limits,
            )
    finally:
        engine.dispose()


def test_query_row_and_response_byte_limits_are_enforced(
    authenticated_client,
    uploaded_sqlite: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = get_settings()
    monkeypatch.setattr(settings, "sql_execution_max_result_bytes", 1024)

    response = execute_request(
        authenticated_client,
        uploaded_sqlite,
        "SELECT printf('%01000d', id) AS content FROM customers ORDER BY id",
    )

    result = response.json()
    assert result["status"] == "success"
    assert result["truncated"] is True
    assert result["row_count"] < 4


def test_column_limit_is_enforced(
    authenticated_client,
    uploaded_sqlite: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(get_settings(), "sql_execution_max_columns", 1)

    response = execute_request(
        authenticated_client,
        uploaded_sqlite,
        "SELECT id, name FROM customers",
    )

    assert response.status_code == 200
    assert response.json()["status"] == "failed"
    assert response.json()["error"] == "The database could not complete this read-only query."


def test_database_failure_is_sanitized_and_recorded(
    authenticated_client,
    uploaded_sqlite: str,
    test_session_factory,
) -> None:
    response = execute_request(
        authenticated_client,
        uploaded_sqlite,
        "SELECT unavailable_extension_function('secret-value')",
    )

    assert response.status_code == 200
    result = response.json()
    assert result["status"] == "failed"
    assert result["error"] == "The database could not complete this read-only query."
    assert "secret-value" not in response.text
    with test_session_factory() as session:
        history = session.get(QueryHistory, UUID(result["execution_id"]))
        assert history is not None
        assert history.execution_status == "failed"
        assert history.generated_sql is not None
        assert history.generated_sql.casefold() == (
            "select unavailable_extension_function('[redacted]')"
        )


def test_execution_metadata_remains_after_result_cache_expires(
    authenticated_client,
    uploaded_sqlite: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.sql import execution_service

    result = execute_request(
        authenticated_client,
        uploaded_sqlite,
        "SELECT name FROM customers LIMIT 1",
    ).json()
    monkeypatch.setattr(
        execution_service.execution_result_cache,
        "get",
        lambda _user_id, _execution_id: None,
    )

    response = authenticated_client["client"](
        "GET",
        f"/api/v1/executions/{result['execution_id']}",
        headers=authenticated_client["headers"],
    )

    assert response.status_code == 200
    assert response.json()["status"] == "results_expired"
    assert response.json()["connection_id"] == uploaded_sqlite
    assert response.json()["created_at"] is not None
    assert response.json()["rows"] == []


def test_invalid_conversation_and_page_limits_are_rejected_without_history(
    authenticated_client,
    uploaded_sqlite: str,
    connection_settings,
    test_session_factory,
) -> None:
    invalid_conversation = execute_request(
        authenticated_client,
        uploaded_sqlite,
        "SELECT 1",
        conversation_id=str(uuid4()),
    )
    too_many_rows = execute_request(
        authenticated_client,
        uploaded_sqlite,
        "SELECT 1",
        page_size=10000,
    )
    with test_session_factory() as session:
        history_count = len(list(session.scalars(select(QueryHistory))))

    assert invalid_conversation.status_code == 404
    assert too_many_rows.status_code == 422
    assert history_count == 0


class _FakePGResult:
    def __init__(self) -> None:
        self._rows = [(1,), (2,)]

    def keys(self):
        return ["value"]

    def fetchmany(self, size: int):
        batch, self._rows = self._rows[:size], self._rows[size:]
        return batch

    def close(self) -> None:
        return None


class _FakePGTransaction:
    is_active = True

    def __init__(self) -> None:
        self.rolled_back = False

    def rollback(self) -> None:
        self.rolled_back = True
        self.is_active = False


class _FakePGConnection:
    def __init__(self) -> None:
        self.statements: list[str] = []
        self.transaction = _FakePGTransaction()
        self.closed = False

    def __enter__(self):
        return self

    def __exit__(self, *_args) -> None:
        self.closed = True

    def begin(self):
        return self.transaction

    def exec_driver_sql(self, statement: str):
        self.statements.append(statement)

    def execution_options(self, **_options):
        return self

    def execute(self, _statement):
        return _FakePGResult()


class _FakePGEngine:
    def __init__(self, connection: _FakePGConnection) -> None:
        self.connection = connection

    def connect(self):
        return self.connection


def test_postgresql_executor_sets_read_only_transaction_timeout_and_rolls_back() -> None:
    connection = _FakePGConnection()
    limits = ExecutionLimits(
        timeout_seconds=2.5,
        default_page_size=100,
        max_page_size=500,
        max_offset=10000,
        max_columns=10,
        max_result_bytes=10000,
        max_concurrent_per_user=1,
        cache_ttl_seconds=60,
        cache_max_bytes=100000,
        cache_max_entries=10,
    )

    from app.sql.executor import execute_validated_sql

    result = execute_validated_sql(
        _FakePGEngine(connection),  # type: ignore[arg-type]
        "postgresql",
        "SELECT 1 AS value",
        page_size=10,
        offset=0,
        limits=limits,
    )

    assert result.rows == [[1], [2]]
    assert connection.statements == [
        "SET TRANSACTION READ ONLY",
        "SET LOCAL statement_timeout = '2500ms'",
    ]
    assert connection.transaction.rolled_back is True
    assert connection.closed is True


def test_per_user_concurrency_limiter_rejects_excess_and_releases() -> None:
    limiter = UserExecutionLimiter()
    user_id = uuid4()
    limiter.acquire(user_id, maximum=1)
    with pytest.raises(TooManyConcurrentExecutionsError):
        limiter.acquire(user_id, maximum=1)
    limiter.release(user_id)
    limiter.acquire(user_id, maximum=1)
    limiter.release(user_id)
